from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..icons import ICONS

register = template.Library()


@register.simple_tag
def icon(name, size=16, css_class=''):
    """Render a Lucide icon inline: {% icon "sparkles" 18 %}"""
    body = ICONS.get(name)
    if body is None:
        return ''
    return format_html(
        '<svg class="icon {}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true" focusable="false">{}</svg>',
        css_class, size, size, mark_safe(body),
    )


@register.filter
def clamp_pct(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, round(value)))


@register.filter
def ring_offset(value, circumference=276.46):
    """stroke-dashoffset for a progress ring of radius 44 (2πr ≈ 276.46)."""
    pct = clamp_pct(value)
    return round(float(circumference) * (1 - pct / 100), 2)


@register.filter
def in_list(value, container):
    try:
        return value in container
    except TypeError:
        return False


@register.filter
def level_label(score):
    try:
        score = int(score)
    except (TypeError, ValueError):
        return ''
    if score >= 80:
        return 'Advanced'
    if score >= 40:
        return 'Intermediate'
    return 'Beginner'


@register.filter
def days_ago(value):
    from django.utils import timezone

    if not value:
        return ''
    days = (timezone.now() - value).days
    if days <= 0:
        return 'Today'
    if days == 1:
        return 'Yesterday'
    if days < 7:
        return f'{days} days ago'
    weeks = days // 7
    return f'{weeks} week{"s" if weeks > 1 else ""} ago'


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Rebuild the current query string with some keys replaced."""
    params = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()
