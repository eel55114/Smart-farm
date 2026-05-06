import hashlib
import os

import requests
from flask import Flask, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from db_manager.manager import DBManager

app = Flask(__name__)
