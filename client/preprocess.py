# coding:utf-8
# import ptvsd
# addr = ("192.168.31.222", 5678)
# ptvsd.enable_attach(address=addr, redirect_output=True)
# ptvsd.wait_for_attach()
import cv2
import tensorflow as tf
import numpy as np
import ffmpeg
import json

import socket
import sys
import os
import struct
import copy
import time

from utils.imgutils import feature_maps_to_image, sort_fmaps

class CompressorObj:
    def __init__(self):
        pass

    def jpeg_enc(self, feature_maps, quality):
        """
        feature_maps: output tensor of feature maps in shape (1, 78, 78, 128)
        quality: quality of JPEG lossy compression from 0 - 100
        return: sliced image of feature maps, pixel from 0 - 255
        """
        shape = (8, 16)
        fmap_images_with_info = feature_maps_to_image(feature_maps, shape, is_display=0, is_save=0)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        result, encimg = cv2.imencode('.jpg', fmap_images_with_info[0][0], encode_param)
        self.compressed_mem = len(encimg)
        print(len(encimg), "length of encoded image")
        res = (encimg, fmap_images_with_info[0][1])
        return res
    
    def webp_enc(self, x, quality):
        shape = (8, 16)
        data = copy.copy(x)
        fmap_images_with_info = feature_maps_to_image(data, shape, is_display=0, is_save=0)
        encode_param = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
        result, encimg = cv2.imencode('.webp', fmap_images_with_info[0][0], encode_param)
        self.compressed_mem = len(encimg)
        print(len(encimg), "length of encoded image")
        res = (encimg, fmap_images_with_info[0][1])
        return res

    def h264_enc(self, x, info):
        crf = info[0]
        preset = info[1]
        feature_maps = copy.copy(x)
        min_val, max_val = feature_maps.min(), feature_maps.max()
        dl, feature_maps = sort_fmaps(feature_maps, 'lum')
        data_name = 'tmp/data'
        b = b''
        for idx, item in enumerate(dl):
            b += feature_maps[item[0]].tobytes()
        with open(data_name, 'wb') as f:
            f.write(b)
            f.close()
        out, _ = (ffmpeg.input(data_name, framerate=60, f='rawvideo', s='78x78', pix_fmt='gray'). \
            output('pipe:', preset=preset,
                   pix_fmt='yuv420p', vcodec='libx264', f='h264', crf=crf). \
            run(capture_stdout=True, quiet=True))
        self.compressed_mem = len(out)
        return (out, dl, (min_val, max_val))

class Preprocessor:
    def __init__(self):
         # tensorflow graph
        self.__model_path = './model/part1.pb'
        self.__name = 'part1'
        self.__input_tensor_name = 'input:0'
        self.__output_tensor_name = 'Pad_5:0'
        self.sess = self.__read_model(self.__model_path, self.__name, is_onecore=False)
        self.input1 = self.sess.graph.get_tensor_by_name('{}/{}'.format(self.__name, self.__input_tensor_name))
        self.output1 = self.sess.graph.get_tensor_by_name('{}/{}'.format(self.__name, self.__output_tensor_name))
        # compression object
        self.compressor = CompressorObj()
        self.buffer = bytearray(10000000)
        # meta data
        self.shape = (1, 78, 78, 128)
        self.batch_size = self.shape[0]
        self.w = self.shape[1]
        self.h = self.shape[2]
        self.channels = self.shape[3]
        self.dtype_header = np.float16
        self.dtype_payload = np.uint8
        self.payload_length = self.batch_size * 78 * 78 * 128
        self.header_length = self.batch_size * 2 * 2 + 1
        self.header = bytes(self.header_length)
        self.payload = bytes(self.payload_length)
        self.results = bytes(self.header_length+self.payload_length)
    
    def __setitem__(self, k, v):
        self.k = v

    def __read_model(self, path, name, is_onecore=True):
        """
        path: the location of pb file path
        name: name of tf graph
        return: tf.Session()
        """
        sess = tf.Session()
        # use one cpu core
        if is_onecore:
            session_conf = tf.ConfigProto(
                intra_op_parallelism_threads=1,
                inter_op_parallelism_threads=1)
            sess = tf.Session(config=session_conf)
        
        mode = 'rb'
        with tf.gfile.FastGFile(path, mode) as f:
            graph_def = tf.GraphDef()
            graph_def.ParseFromString(f.read())
            sess.graph.as_default()
            tf.import_graph_def(graph_def, name=name)
        return sess

    def fill_buffer(self, data, connection):
        # connection.sendall(data)
        pass

    def read_buffer(self, connection):
        header = bytearray(4)
        connection.recv_into(header, 4)
        # # 4 bytes presents data length
        to_read = struct.unpack('>L', header)[0]
        data_length = to_read
        # buf = bytearray(data_length)
        # view = memoryview(buf)
        view = memoryview(self.buffer)
        # read = 0
        while to_read:
            # print(to_read)
            nbytes = connection.recv_into(view, to_read)
            view = view[nbytes:]
            to_read -= nbytes
        # data = np.frombuffer(self.buffer, np.uint8, data_length)
        data = self.buffer[0:data_length]
        self.buffer = bytearray(10000000)
        return data

    def preprocess_image(self, image, image_size=(608, 608)):
        image_cp = np.copy(image).astype(np.float32)
        # resize image
        image_rgb = cv2.cvtColor(image_cp, cv2.COLOR_BGR2RGB)
        image_resized = cv2.resize(image_rgb, image_size)
        # normalize
        image_normalized = image_resized.astype(np.float32) / 225.0
        # expand dimension
        image_expanded = np.expand_dims(image_normalized, axis=0)
        return image_expanded

    def inference(self, mode, img_bytes, info):
        """
        mode: 0:jpeg 1:webp 2:h264
        img: bytes array of image
        return: info payload in bytes
        """
        data = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(data, 1)
        img_preprossed = self.preprocess_image(img)
        feature_maps = self.sess.run(self.output1, feed_dict={self.input1: img_preprossed})
        h_1 = bytes([self.batch_size])
        h_2 = bytes([mode])
        header_tmp = b''
        payload_tmp = b''
        res_bytes = b''
        if mode == 0 or mode == 1:
            quality = info
            if mode == 0:
                fmaps_bytes_with_info = self.compressor.jpeg_enc(feature_maps, quality)
            if mode == 1:
                fmaps_bytes_with_info = self.compressor.webp_enc(feature_maps, quality)
            fmaps_data = fmaps_bytes_with_info[0]
            header_tmp += np.array(fmaps_bytes_with_info[1], dtype=self.dtype_header).tobytes()
            payload_tmp += np.array(fmaps_data, dtype=self.dtype_payload).tobytes()
            l1 = struct.pack('<H', len(header_tmp))
            lp = struct.pack('>I', len(payload_tmp))
            res_bytes = h_1 + h_2 + l1 + lp + header_tmp + payload_tmp
        if mode == 2:
            fmaps_bytes_with_info = self.compressor.h264_enc(feature_maps, info)
            fmaps_data = fmaps_bytes_with_info[0]
            dl = json.dumps(fmaps_bytes_with_info[1]).encode('utf-8')
            header_tmp += np.array(fmaps_bytes_with_info[2], dtype=self.dtype_header).tobytes()
            payload_tmp += fmaps_data
            # get bytes length of header and payload
            l1 = struct.pack('<H', len(dl))
            l2 = struct.pack('<H', len(header_tmp))
            lp = struct.pack('>I', len(payload_tmp))
            res_bytes = h_1 + h_2 + l1 + l2 + lp + dl + header_tmp + payload_tmp
        return res_bytes

def main():
    # socket
    server_address = './uds_socket'
    try:
        os.unlink(server_address)
    except OSError:
        if os.path.exists(server_address):
            raise
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(server_address)
    # compressor
    compressor = CompressorObj()
    # preprocessor
    preprocessor = Preprocessor()
    # main loop
    sock.listen(1)
    print("Waiting for connections")
    connection, client_address = sock.accept()
    # connection.setblocking(0)
    while(1):
        img_bytes = preprocessor.read_buffer(connection)
        # jpeg
        res_bytes = preprocessor.inference(0, img_bytes, 70)
        # webp
        # res_bytes = preprocessor.inference(1, img_bytes, 70)
        # h264
        # res_bytes = preprocessor.inference(2, img_bytes, (25, 'ultrafast'))
        preprocessor.fill_buffer(res_bytes, connection)
        print(len(img_bytes), len(res_bytes))
        connection.recv(0)


if __name__ == "__main__":
    main()