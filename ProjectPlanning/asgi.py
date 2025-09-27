"""
ASGI config for ProjectPlanning project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import dotenv, os

dotenv.load_dotenv()

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProjectPlanning.settings')

application = get_asgi_application()
