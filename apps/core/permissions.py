from rest_framework.permissions import BasePermission


class IsTrustAgent(BasePermission):
    """Only active Trust & Safety agents may use the review console."""

    message = "Trust & Safety agent access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and getattr(user, "role", None) == "agent"
        )


class IsMarketplaceUser(BasePermission):
    """Active owners and sitters (the people who use the marketplace itself)."""

    message = "Marketplace account required."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and getattr(user, "role", None) in ("owner", "sitter")
        )
