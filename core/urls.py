
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('skills/', views.manage_skills, name='skills'),
    path('skills/<int:pk>/update/', views.skill_update, name='skill_update'),

    # Profile & resume
    path('profile/', views.profile, name='profile'),
    path('profile/preferences/', views.career_preferences, name='career_preferences'),
    path('profile/account/', views.account_settings, name='account_settings'),
    path('profile/resume/upload/', views.cv_upload, name='cv_upload'),
    path('profile/resume/<int:pk>/review/', views.cv_review, name='cv_review'),
    path('profile/resume/<int:pk>/file/', views.cv_download, name='cv_download'),
    path('profile/resume/<int:pk>/delete/', views.cv_delete, name='cv_delete'),

    # Opportunities & matching
    path('opportunities/', views.opportunity_list, name='opportunities'),
    path('opportunities/<int:pk>/', views.opportunity_detail, name='opportunity_detail'),
    path('opportunities/<int:pk>/save/', views.opportunity_save, name='opportunity_save'),
    path('opportunities/<int:pk>/apply/', views.opportunity_apply, name='opportunity_apply'),
    path('saved/', views.saved_list, name='saved'),
    path('skill-gap/', views.skill_gap, name='skill_gap'),
    path('search/', views.search, name='search'),

    # Information pages
    path('help/', views.help_page, name='help'),
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),

    # Password reset (emails print to the console in development)
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='core/auth/password_reset.html',
        email_template_name='core/auth/password_reset_email.txt',
        subject_template_name='core/auth/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done')), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/auth/password_reset_done.html'), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/auth/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete')), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/auth/password_reset_complete.html'), name='password_reset_complete'),
]
