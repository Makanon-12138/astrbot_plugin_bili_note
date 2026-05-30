import os

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

BV_REGEX = r"(?:\?.*)?(?:https?:\/\/)?(?:www\.)?(?:bilibili\.com\/video\/(BV[a-zA-Z0-9]+)|b23\.tv\/([a-zA-Z0-9]+))\/?(?:\?.*)?|BV[a-zA-Z0-9]+"

PLUGIN_NAME = "astrbot_plugin_bili_note"

DATA_DEFAULT = {
    "credential": None,
}

REQUEST_TIMEOUT = 10
