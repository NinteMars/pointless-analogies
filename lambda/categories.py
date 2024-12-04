import random
import boto3
import json
import os
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    categories = ["chair", "hat", "boat", "shoe", "wig", "hair tie", "apple", "toothbrush",
              "fork", "shirt", "belt", "table", "bat", "car", "pen", "bicycle",
              "ice cube tray", "knife", "purse", "cat"]
    result = random.choice(categories)
    return result