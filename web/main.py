#packages for mask detection

# Stream video

import numpy as np
from cv2 import cv2
import tensorflow as tf
from object_detection.utils import label_map_util
from object_detection.utils import config_util
from object_detection.utils import visualization_utils as viz_utils
from object_detection.builders import model_builder
from playsound import playsound

# web server and socket
from flask import Flask, render_template, request, jsonify, redirect
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

import json, os

#  variables y settings

data = dict()
alarm_actual_state = False
ALLOWED_EXTENSIONS = ['mp3']
UPLOAD_FOLDER = os.path.join(os.path.abspath(os.getcwd()), 'static')
UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'alarms')

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

socketio = SocketIO(app)



def detect(image, detection_model):
    image, shapes = detection_model.preprocess(image)
    prediction_dict = detection_model.predict(image, shapes)
    detections = detection_model.postprocess(prediction_dict, shapes)

    return detections, prediction_dict, tf.reshape(shapes, [-1])


def run(label_map_path, config_file_path, checkpoint_path):

    # Enable GPU dynamic memory allocation
    gpus = tf.config.experimental.list_physical_devices('GPU')
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)

    # Load pipeline config and build a detection model
    configs = config_util.get_configs_from_pipeline_file(config_file_path)
    model_config = configs['model']
    detection_model = model_builder.build(model_config=model_config, is_training=False)

    # Restore checkpoint
    ckpt = tf.compat.v2.train.Checkpoint(model=detection_model)
    ckpt.restore(checkpoint_path).expect_partial()

    category_index = label_map_util.create_category_index_from_labelmap(label_map_path, use_display_name=True)

    videoStreamAddress = "http://192.168.1.82:4747/video"

    cap = cv2.VideoCapture(videoStreamAddress) #esto básicamente
    
    while True:
        # Read frame from camera
        ret, image_np = cap.read()

        input_tensor = tf.convert_to_tensor(np.expand_dims(image_np, 0), dtype=tf.float32)
        detections, predictions_dict, shapes = detect(input_tensor, detection_model)

        detection_boxes = detections['detection_boxes'][0].numpy()
        detection_classes = detections['detection_classes'][0].numpy()
        detection_scores = detections['detection_scores'][0].numpy()

        indexes = np.array(tf.image.non_max_suppression(
            detection_boxes,
            detection_scores,
            max_output_size=100,
            iou_threshold=0.5,
            score_threshold=0.3))

        detection_boxes = detection_boxes[indexes]
        detection_classes = detection_classes[indexes]
        detection_scores = detection_scores[indexes]

        label_id_offset = 1
        image_np_with_detections = image_np.copy()
        bb_color = 'green'


        if indexes.shape != 0:
            viz_utils.visualize_boxes_and_labels_on_image_array(
                image_np_with_detections,
                detection_boxes,
                (detection_classes + label_id_offset).astype(int),
                detection_scores,
                category_index,
                use_normalized_coordinates=True,
                max_boxes_to_draw=10,
                min_score_thresh=.30,
                agnostic_mode=False,
                semaphore_mode=True)

            # si cualquiera de las personas frente a la cámara está usando mal la mascarilla o no tiene, marcar recuadro rojo
            if any(c == 1 or c == 3 for c in detection_classes):
                bb_color = 'green' #rojo
                # envia mensaje al socket avisando a la alarma para que se encienda
                emit('alarm', {'alarm': 1}, namespace='/', broadcast=True)
            # sino, todo ok, verde
            else:
                bb_color = 'blue' #verde
                # envia mensaje al socket avisando a la alarma que se apague en caso de estar sonando
                emit('alarm', {'alarm': 0}, namespace='/', broadcast=True)
            viz_utils.draw_bounding_box_on_image_array(
                image_np_with_detections,
                0, 0, 1, 1, 
                color = bb_color,
                thickness = 20)

        print(detection_boxes, detection_classes, detection_scores)
        print((detection_classes + label_id_offset).astype(int))
        
        #if any(c == 1 or c == 3 for c in detection_classes):
        #   playsound('templates/alarm.mp3')

        frame = cv2.resize(image_np_with_detections, (800, 600))

        # Display output
        #cv2.imshow('MaskON: Uso correcto de mascarilla', cv2.resize(image_np_with_detections, (800, 600)))
        # encode OpenCV raw frame to jpg and displaying it
        
        ret, jpeg = cv2.imencode('.jpg', frame)
        frame_encoded_jpeg = jpeg.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_encoded_jpeg + b'\r\n\r\n')
    
        if cv2.waitKey(25) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# RUTAS

@app.route('/')
def index():
    # rendering webpage
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(run(
                        label_map_path=PATH_TO_LABELMAP,
                        config_file_path=PATH_TO_CONFIG,
                        checkpoint_path=PATH_TO_CHECKPOINT),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def old_index():
    return redirect("home", code=303)


@app.route('/home')
def index():
    resp = render_template("template.html")
    return resp


@app.route('/settings')
def settings():
    resp = render_template("settings.html")
    return resp


@app.route('/test')
def test():
    print("hello")
    return "nothing"


@app.route('/get_config')
def get_settings():
    return jsonify(data)


@app.route('/post_config', methods=['POST'])
def post_settings():
    global data

    if request.method == 'POST':
        data = request.get_json()

        with open('config.json', 'w') as fp:
            json.dump(data, fp)

    return '200'


@app.route('/post_file', methods=['POST'])
def post_file():
    f = request.files['file']
    print(os.path.join(app.config['UPLOAD_FOLDER'], f.filename))
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(f.filename)))

    return '200'


@socketio.on('alarm_change')
def alarm_event(json):
    print(json)
    emit('my response', json, broadcast=True)


if __name__ == '__main__':
    PATH_TO_LABELMAP = r"C:\Users\matia\Documents\Scripts\PDI\training_resources\training\001\label_map.pbtxt"
    PATH_TO_CONFIG = r"C:\Users\matia\Documents\Scripts\PDI\training_resources\training\001\pipeline.config"
    PATH_TO_CHECKPOINT = r"C:\Users\matia\Documents\Scripts\PDI\training_resources\training\001\ckpt-17"

    #run(label_map_path=PATH_TO_LABELMAP, config_file_path=PATH_TO_CONFIG, checkpoint_path=PATH_TO_CHECKPOINT)
    #app.run(host='127.0.0.1',port='5000', debug=True)
    socketio.run(app)