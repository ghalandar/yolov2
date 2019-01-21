import numpy as np
import copy
import cv2

from dev import graph_editor as ge
from detect import *
from utils import *
from detect import *

class Compressor:
    def __init__(self):
        self.buffer = []


    def fill_buffer(self, data):
        compressed_data = self.compress(data)
        self.buffer.append(compressed_data)
        return 0

    def read_buffer(self, buf):
        data = self.get_from_buf()
        return data

    def get_from_buf(self):
        return self.buffer[0]
    
    def compress(self, data):
        data_copy = copy.copy(data)
        """
        compress main loop here
        """
        compressed_data = data_copy
        return compressed_data


if __name__ == "__main__":
    # initialize
    sess1 = ge.read_model('./model/splitted_models/part1.pb')
    sess2 = ge.read_model('./model/splitted_models/yolo.pb')
    tensor_names = [t.name for op in sess1.graph.get_operations()
                    for t in op.values()]
    input1 = sess1.graph.get_tensor_by_name("part1/input:0")
    output1 = sess1.graph.get_tensor_by_name("part1/Pad_5:0")

    input2 = sess2.graph.get_tensor_by_name("yolo/Pad_5:0")
    output2 = sess2.graph.get_tensor_by_name("yolo/output:0")

    input3 = sess2.graph.get_tensor_by_name("yolo/input:0")
    output3 = sess2.graph.get_tensor_by_name("yolo/output:0")
    compressor = Compressor()
    # main loop
    img_orig = cv2.imread('./pedes_images/01-20170320211734-25.jpg')
    img = preprocess_image(img_orig)
    output_feature = sess1.run(output1, feed_dict={input1: img})
    get_feature_map(output_feature, 1)
    
    flag = compressor.fill_buffer(output_feature)
    if flag is not 0:
        raise "Error"
    compressed_data = compressor.get_from_buf()
    res = sess2.run(output2, feed_dict={input2: compressed_data})
    start = time.time()
    output_decoded = decode(model_output=output2, output_sizes=(608//32, 608//32),
                            num_class=len(class_names), anchors=anchors)
    bboxes, obj_probs, class_probs = sess2.run(
        output_decoded, feed_dict={input2: output_feature})
    
    img_detection = draw_detection(
        img_orig, bboxes, scores, class_max_index, class_names)
    # cv2.imwrite("./data/detection.jpg", img_detection)
    end = time.time()
    print('YOLO_v2 detection has done! spent {} seconds'.format(end - start))
    
    cv2.imshow("detection_results", img_detection)
    cv2.waitKey(0)
    cv2.destroyAllWindows()