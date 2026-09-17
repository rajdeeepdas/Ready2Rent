from django.contrib.auth import authenticate, password_validation
from rest_framework import serializers

from .models import User, UserRole


class UserSerializer(serializers.ModelSerializer):
    """Profile as seen by the user themself. Role and email are never writable here."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "role", "date_joined"]
        read_only_fields = ["id", "email", "role", "date_joined"]


class RegisterSerializer(serializers.Serializer):
    """Homeowner self-signup. The role is forced server-side; any client-supplied
    role / is_staff / is_superuser is ignored because they are not declared fields."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, allow_null=True)

    def validate_email(self, value: str) -> str:
        normalized = User.objects.normalize_email(value).lower()
        if User.objects.filter(email=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate(self, attrs):
        # Run Django's configured validators with user attributes so the similarity
        # validator can compare against email / names.
        probe = User(
            email=attrs["email"], first_name=attrs["first_name"], last_name=attrs["last_name"]
        )
        password_validation.validate_password(attrs["password"], user=probe)
        return attrs

    def create(self, validated):
        return User.objects.create_user(
            email=validated["email"],
            password=validated["password"],
            first_name=validated["first_name"],
            last_name=validated["last_name"],
            phone=validated.get("phone") or None,
            role=UserRole.HOMEOWNER,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    # One message for unknown email, wrong password, and inactive account.
    GENERIC_ERROR = "Invalid email or password."

    def validate(self, attrs):
        email = User.objects.normalize_email(attrs["email"]).lower()
        # ModelBackend returns None for inactive users too, so all three failure
        # modes collapse into the same branch by construction.
        user = authenticate(self.context.get("request"), username=email, password=attrs["password"])
        if user is None:
            raise serializers.ValidationError({"detail": self.GENERIC_ERROR}, code="authentication")
        attrs["user"] = user
        return attrs
