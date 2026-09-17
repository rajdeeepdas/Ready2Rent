"""factory_boy factories for every model. Consistent by default: a factory-built
Application always has a property owned by its homeowner and a suite on that property."""

import factory
from django.utils import timezone

from accounts.models import User, UserRole
from applications.enums import (
    ApplicationStatus,
    ComplianceItemType,
    DocumentType,
    PermitType,
    SuiteType,
    VisitType,
)
from applications.models import (
    Application,
    ApplicationStatusHistory,
    ComplianceItem,
    Document,
    Permit,
    Property,
    Suite,
    Visit,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    role = UserRole.HOMEOWNER
    # Hashed before the INSERT; UserFactory(password="raw") hashes the given value.
    password = factory.django.Password("test-pass-123")


class PropertyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Property

    owner = factory.SubFactory(UserFactory, role=UserRole.HOMEOWNER)
    street_address = factory.Sequence(lambda n: f"{100 + n} 12 Ave SW")
    postal_code = "T2R 0G8"
    year_built = 1975


class SuiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Suite

    property = factory.SubFactory(PropertyFactory)
    suite_type = SuiteType.LEGALIZE_EXISTING


class ApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Application

    homeowner = factory.SubFactory(UserFactory, role=UserRole.HOMEOWNER)
    property = factory.SubFactory(PropertyFactory, owner=factory.SelfAttribute("..homeowner"))
    suite = factory.SubFactory(SuiteFactory, property=factory.SelfAttribute("..property"))
    status = ApplicationStatus.INTAKE


class StatusHistoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApplicationStatusHistory

    application = factory.SubFactory(ApplicationFactory)
    from_status = None
    to_status = ApplicationStatus.INTAKE
    changed_by = factory.SelfAttribute("application.homeowner")


class ComplianceItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ComplianceItem

    application = factory.SubFactory(ApplicationFactory)
    item_type = ComplianceItemType.EGRESS_WINDOW


class PermitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Permit

    application = factory.SubFactory(ApplicationFactory)
    permit_type = PermitType.BUILDING


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    application = factory.SubFactory(ApplicationFactory)
    doc_type = DocumentType.SITE_PLAN


class VisitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Visit

    application = factory.SubFactory(ApplicationFactory)
    visit_type = VisitType.SITE_ASSESSMENT
    scheduled_for = factory.LazyFunction(timezone.now)
