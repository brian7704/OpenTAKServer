import colorlog
from flask_sqlalchemy import SQLAlchemy
from models.Base import Base

db = SQLAlchemy(model_class=Base)

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s[%(asctime)s] - %(levelname)s - %(name)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S"))

logger = colorlog.getLogger('OpenTAKServer')
logger.setLevel('DEBUG')
if not logger.hasHandlers():
    logger.addHandler(handler)
