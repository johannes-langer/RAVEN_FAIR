# -*- coding: utf-8 -*-


import xml.etree.ElementTree as ET

import cv2
import numpy as np
from const import DEFAULT_WIDTH, IMAGE_SIZE
from rendering import render_entity
from itertools import groupby

from pycocotools import mask as msk


class Bunch:
    """Dummy class"""
    def __init__(self, **kwds):
        self.__dict__.update(kwds)


def get_real_bbox(entity_bbox, entity_type, entity_size, entity_angle):
    assert entity_type != "none"
    center = (int(entity_bbox[1] * IMAGE_SIZE), int(entity_bbox[0] * IMAGE_SIZE))
    M = cv2.getRotationMatrix2D(center, entity_angle, 1)
    unit = min(entity_bbox[2], entity_bbox[3]) * IMAGE_SIZE / 2
    delta = DEFAULT_WIDTH * 1.5 / IMAGE_SIZE
    if entity_type == "circle":
        radius = unit * entity_size
        real_bbox = [center[1] * 1.0 / IMAGE_SIZE, center[0] * 1.0 / IMAGE_SIZE, 2 * radius / IMAGE_SIZE + delta, 2 * radius / IMAGE_SIZE + delta]
    else:
        if entity_type == "triangle":
            dl = int(unit * entity_size)
            homo_pts = np.array([[center[0], center[1] - dl, 1], 
                                 [center[0] + int(dl / 2.0 * np.sqrt(3)), center[1] + int(dl / 2.0), 1], 
                                 [center[0] - int(dl / 2.0 * np.sqrt(3)), center[1] + int(dl / 2.0), 1]], 
                                np.int32)
        if entity_type == "square":
            dl = int(unit / 2 * np.sqrt(2) * entity_size)
            homo_pts = np.array([[center[0] - dl, center[1] - dl, 1],
                                 [center[0] - dl, center[1] + dl, 1], 
                                 [center[0] + dl, center[1] + dl, 1], 
                                 [center[0] + dl, center[1] - dl, 1]],
                                np.int32)
        if entity_type == "pentagon":
            dl = int(unit * entity_size)
            homo_pts = np.array([[center[0], center[1] - dl, 1],
                                 [center[0] - int(dl * np.cos(np.pi / 10)), center[1] - int(dl * np.sin(np.pi / 10)), 1],
                                 [center[0] - int(dl * np.sin(np.pi / 5)), center[1] + int(dl * np.cos(np.pi / 5)), 1],
                                 [center[0] + int(dl * np.sin(np.pi / 5)), center[1] + int(dl * np.cos(np.pi / 5)), 1],
                                 [center[0] + int(dl * np.cos(np.pi / 10)), center[1] - int(dl * np.sin(np.pi / 10)), 1]],
                                np.int32)
        if entity_type == "hexagon":
            dl = int(unit * entity_size)
            homo_pts = np.array([[center[0], center[1] - dl, 1],
                                 [center[0] - int(dl / 2.0 * np.sqrt(3)), center[1] - int(dl / 2.0), 1],
                                 [center[0] - int(dl / 2.0 * np.sqrt(3)), center[1] + int(dl / 2.0), 1],
                                 [center[0], center[1] + dl, 1],
                                 [center[0] + int(dl / 2.0 * np.sqrt(3)), center[1] + int(dl / 2.0), 1],
                                 [center[0] + int(dl / 2.0 * np.sqrt(3)), center[1] - int(dl / 2.0), 1]],
                                np.int32)
        after_pts = np.dot(M, homo_pts.T)
        min_x = min(after_pts[1, :]) / IMAGE_SIZE
        max_x = max(after_pts[1, :]) / IMAGE_SIZE
        min_y = min(after_pts[0, :]) / IMAGE_SIZE
        max_y = max(after_pts[0, :]) / IMAGE_SIZE
        real_bbox = [(min_x + max_x) / 2, (min_y + max_y) / 2, max_x - min_x + delta, max_y - min_y + delta] 
    return list(np.round(real_bbox, 4))


def get_mask(entity_bbox, entity_type, entity_size, entity_angle):
    dummy_entity = Bunch()
    dummy_entity.bbox = entity_bbox
    dummy_entity.type = Bunch(get_value = lambda : entity_type)
    dummy_entity.size = Bunch(get_value = lambda : entity_size)
    dummy_entity.color = Bunch(get_value = lambda : 0)
    dummy_entity.angle = Bunch(get_value = lambda : entity_angle)
    mask = np.ceil(render_entity(dummy_entity) / 255).astype(int)
    return mask


# ref: https://www.kaggle.com/stainsby/fast-tested-rle
# ref: https://www.kaggle.com/paulorzp/run-length-encode-and-decode
def rle_encode(img):
    '''
    img: numpy array, 1 - mask, 0 - background
    Returns run length as string formated
    '''
    pixels = img.flatten()
    pixels = np.concatenate([[0], pixels, [0]])
    runs = np.where(pixels[1:] != pixels[:-1])[0] + 1
    # runs[1::2] -= runs[::2]
    runs[1::2] -= runs[:-1:2]       #@Jona: Either lost ins 2to3 translation, or this should've been copy-pasted better...
    return "[" + ",".join(str(x) for x in runs) + "]"
 

def rle_decode(mask_rle, shape):
    '''
    mask_rle: run-length as string formated (start length)
    shape: (height,width) of array to return 
    Returns numpy array, 1 - mask, 0 - background
    '''
    s = mask_rle[1:-1].split(",")
    starts, lengths = [np.asarray(x, dtype=int) for x in (s[0:][::2], s[1:][::2])]
    starts -= 1
    ends = starts + lengths
    img = np.zeros(shape[0] * shape[1], dtype=np.uint8)
    for lo, hi in zip(starts, ends):
        img[lo:hi] = 1
    return img.reshape(shape)


def coco_rle(mask : np.ndarray, api : bool = False):
    '''
    Generates an rle-encoding string which can be used in coco-json formatting. This appears to be much slower than rle_encode, but since the dataset must only be generated _once_ in most cases, it is probably worth to spend the extra generation time to have usable annotations.
    \n Impelements top response of this thread: https://stackoverflow.com/questions/49494337/encode-numpy-array-using-uncompressed-rle-for-coco-dataset

    PARAMETERS
    ----------
    `mask : ndarray` np array binary mask, where 1 is masked and 0 unmasked.
    `api : bool` use cocoapi version of the encoder

    RETURNS
    rle : dict in coco-rle format.
    '''
    rle = {
        'counts': [],
        'size': list(mask.shape)
    }
    counts = rle.get('counts')
    for i, (value, elements) in enumerate(groupby(mask.ravel(order='F'))):
        if i == 0 and value == 1:
            counts.append(0)
        counts.append(len(list(elements)))
    
    return rle if not api else msk.encode(np.asarray(mask, order='F'))


def poly_mask(mask : np.ndarray) -> np.ndarray:
    '''
    Find contours in image for detectron annotation.
    Thanks @JT
    '''
    padded_label_array = np.pad(mask, pad_width = 1, mode = 'constant', constant_values = 0)
    contour = measure.find_contours(padded_label_array)[0]
    contour = np.flip(contour, axis = 1)
    contour = contour - 1
    contour[contour < 0] = 0

    return contour.tolist()
