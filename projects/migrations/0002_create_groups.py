from django.db import migrations

# Nombres de los grupos de Bonita
GROUP_NAMES = [
    "ONG solicitante",
    "ONGs colaboradoras",
    "Consejo Directivo",
]

def create_groups(apps, schema_editor):
    """
    Crea los Grupos de permisos en Django
    """
    Group = apps.get_model('auth', 'Group')
    for group_name in GROUP_NAMES:
        # Esto evita crear duplicados si ya existen
        Group.objects.get_or_create(name=group_name)

def reverse_create_groups(apps, schema_editor):
    """
    Elimina los grupos si deshacemos la migración
    """
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=GROUP_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_groups, reverse_create_groups),
    ]