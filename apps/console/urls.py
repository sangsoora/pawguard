from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("assessments", views.AssessmentViewSet, basename="assessment")
router.register("users", views.UserViewSet, basename="user")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = router.urls
