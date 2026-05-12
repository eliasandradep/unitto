import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'osbeauty-dev-secret-change-me')

_db_url = os.getenv('DATABASE_URL', 'sqlite:///osbeauty.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI']        = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from models import db, User
from themes import get_theme_css

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin.login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_theme():
    from flask_login import current_user
    try:
        if current_user.is_authenticated:
            theme_key = current_user.studio.get_config('active_theme', 'default')
            return {'theme_css': get_theme_css(theme_key)}
    except Exception:
        pass
    return {'theme_css': ''}


from admin import admin_bp
app.register_blueprint(admin_bp)


@app.route('/')
def index():
    return redirect(url_for('admin.dashboard'))


@app.route('/ping')
def ping():
    return 'ok', 200


with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True, port=5001)
