from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops

PAYLOAD_OK = {"message": None, "fieldErrors": [], "code": None}


async def test_search_property_values(call: Call, mm: AsyncMock) -> None:
    homes = [{"zpid": "123", "addressStreet": "1 Main St", "zestimate": 500000.0}]
    mm.gql_call.return_value = {"zestimates": homes}
    assert await call("search_property_values", address="1 Main St, Springfield") == homes
    assert gql_ops(mm) == [("Web_GetZestimate", {"address": "1 Main St, Springfield", "limit": 5})]


async def test_search_property_values_limit(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"zestimates": []}
    assert await call("search_property_values", address="x", limit=2) == []
    assert gql_ops(mm) == [("Web_GetZestimate", {"address": "x", "limit": 2})]


async def test_search_vehicle_values(call: Call, mm: AsyncMock) -> None:
    cars = [{"vin": "1HGCM82633A004352", "name": "2003 Honda Accord", "value": 3500.0}]
    mm.gql_call.return_value = {"vehicles": cars}
    assert await call("search_vehicle_values", vin="1HGCM82633A004352") == cars
    assert gql_ops(mm) == [("VehiclesSearch", {"search": "1HGCM82633A004352", "limit": 5})]


async def test_get_deleted_accounts_only_returns_deleted(call: Call, mm: AsyncMock) -> None:
    deleted = {"id": "a2", "displayName": "Old", "deletedAt": "2026-01-02T00:00:00Z"}
    mm.gql_call.return_value = {"accounts": [
        {"id": "a1", "displayName": "Live", "deletedAt": None}, deleted]}
    assert await call("get_deleted_accounts") == [deleted]
    assert gql_ops(mm) == [("Web_GetDeletedAccounts", {})]


async def test_create_real_estate_account(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSyncedRealEstateAccount": {
        "account": {"id": "a9"}, "errors": PAYLOAD_OK}}
    assert await call("create_real_estate_account", zpid="123", name="Home",
                      subtype="primary_home") == {"id": "a9"}
    assert gql_ops(mm)[0][0] == "Web_CreateZillowAccount"
    assert gql_input(mm) == {"zpid": "123", "name": "Home", "subtype": "primary_home",
                             "currentBalance": 0, "includeInNetWorth": True}


async def test_create_real_estate_account_options(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSyncedRealEstateAccount": {
        "account": {"id": "a9"}, "errors": None}}
    await call("create_real_estate_account", zpid="123", name="Cabin", subtype="vacation_home",
               current_balance=250000, include_in_net_worth=False)
    assert gql_input(mm) == {"zpid": "123", "name": "Cabin", "subtype": "vacation_home",
                             "currentBalance": 250000, "includeInNetWorth": False}


async def test_create_real_estate_account_error(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSyncedRealEstateAccount": {
        "account": None, "errors": {"message": "Invalid zpid", "fieldErrors": []}}}
    with pytest.raises(ToolError, match="Creating the real estate account failed: Invalid zpid"):
        await call("create_real_estate_account", zpid="bad", name="Home", subtype="primary_home")


async def test_create_vehicle_account(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSyncedVehicleAccount": {
        "account": {"id": "v1"}, "errors": PAYLOAD_OK}}
    assert await call("create_vehicle_account", vin="VIN1", name="Car", subtype="car") == {"id": "v1"}
    assert gql_ops(mm)[0][0] == "CreateSyncedVehicleAccount"
    assert gql_input(mm) == {"vin": "VIN1", "name": "Car", "subtype": "car"}


async def test_create_vehicle_account_error(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSyncedVehicleAccount": {
        "account": None,
        "errors": {"message": None, "fieldErrors": [{"field": "vin", "messages": ["Unknown VIN"]}]}}}
    with pytest.raises(ToolError, match="Creating the vehicle account failed: vin: Unknown VIN"):
        await call("create_vehicle_account", vin="x", name="Car", subtype="car")


async def test_undelete_account(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"undeleteAccount": {"undeleted": True, "errors": PAYLOAD_OK}}
    assert await call("undelete_account", account_id="a2") == {"account_id": "a2", "undeleted": True}
    assert gql_ops(mm)[0][0] == "Common_UndeleteAccount"
    assert gql_input(mm) == {"id": "a2"}


async def test_undelete_account_error(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"undeleteAccount": {
        "undeleted": False, "errors": {"message": "Account not found", "fieldErrors": []}}}
    with pytest.raises(ToolError, match="Restoring the account failed: Account not found"):
        await call("undelete_account", account_id="nope")
