from django import template

register = template.Library()

@register.filter(name="has_group")
def has_group(user, group_name):
    """
    Devuelve True si el usuario pertenece al grupo indicado.
    """
    try:
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    except Exception:
        return False