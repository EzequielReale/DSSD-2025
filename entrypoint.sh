#!/usr/bin/env bash
set -e

# Esperar a Postgres si está configurado
if [ -n "$DB_HOST" ]; then
  echo "Esperando a Postgres en $DB_HOST:$DB_PORT..."
  until nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
  done
fi

echo "Aplicando migraciones..."
python manage.py migrate --noinput

echo "Collectstatic..."
python manage.py collectstatic --noinput || true

# Crear superusuario si se definieron variables
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "Creando superusuario (idempotente)..."
  python manage.py shell <<'PYCODE'
import os
from django.contrib.auth import get_user_model
User = get_user_model()
u = os.environ["DJANGO_SUPERUSER_USERNAME"]
e = os.environ["DJANGO_SUPERUSER_EMAIL"]
p = os.environ["DJANGO_SUPERUSER_PASSWORD"]
if not User.objects.filter(username=u).exists():
    User.objects.create_superuser(u, e, p)
PYCODE
fi

echo "Levantando Gunicorn..."
exec gunicorn --workers 3 --timeout 120 --bind 0.0.0.0:${PORT:-8000} ProjectPlanning.wsgi:application