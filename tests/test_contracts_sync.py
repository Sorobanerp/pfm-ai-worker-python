"""Tests contract synchronization and gRPC protobuf integrity."""
import pytest
from src.contracts.pfm.v1 import tenant_admin_service_pb2, user_profile_service_pb2


def test_tenant_admin_contract_stubs():
    req = tenant_admin_service_pb2.ListTenantsRequest(
        page_size=20,
        page_token="",
        status_filter=tenant_admin_service_pb2.SUBSCRIPTION_STATUS_ACTIVE,
        plan_filter=tenant_admin_service_pb2.SUBSCRIPTION_PLAN_INDIVIDUAL_PRO,
    )
    assert req.page_size == 20
    assert req.status_filter == tenant_admin_service_pb2.SUBSCRIPTION_STATUS_ACTIVE
    assert req.plan_filter == tenant_admin_service_pb2.SUBSCRIPTION_PLAN_INDIVIDUAL_PRO


def test_user_profile_contract_stubs():
    req = user_profile_service_pb2.GetUserProfileRequest(
        tenant_id="11111111-1111-4111-8111-111111111111",
        user_id="usr_test_123",
    )
    assert req.tenant_id == "11111111-1111-4111-8111-111111111111"
    assert req.user_id == "usr_test_123"

    budget = user_profile_service_pb2.CategoryBudget(
        category_id="supermercado",
        category_name="Supermercado",
        monthly_cap="1500.0000",
        alert_threshold_percentage=80,
    )
    assert budget.monthly_cap == "1500.0000"
    assert budget.alert_threshold_percentage == 80
