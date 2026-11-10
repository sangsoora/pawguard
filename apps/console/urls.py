from django.urls import path
from rest_framework.routers import DefaultRouter

from . import auth, views

router = DefaultRouter()
router.register("assessments", views.AssessmentViewSet, basename="assessment")
router.register("messages", views.ModerationViewSet, basename="moderation")
router.register("users", views.UserViewSet, basename="user")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("auth/csrf/", auth.CsrfView.as_view()),
    path("auth/login/", auth.LoginView.as_view()),
    path("auth/logout/", auth.LogoutView.as_view()),
    path("auth/me/", auth.MeView.as_view()),
    *router.urls,
]
