from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import LoginForm, RegistrationForm
from .helpers import safe_next


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html')


@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user, backend='core.backends.EmailOrUsernameBackend')
        messages.success(request, 'Welcome to SkillMatch! Next: upload your resume and confirm your skills.')
        return redirect('profile')
    return render(request, 'core/auth/register.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def user_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        if not form.cleaned_data.get('remember_me'):
            request.session.set_expiry(0)  # end session when the browser closes
        return redirect(safe_next(request, 'dashboard'))
    return render(request, 'core/auth/login.html', {'form': form})


def user_logout(request):
    if request.method == 'POST':
        logout(request)
        return redirect('home')

    return redirect('dashboard')
