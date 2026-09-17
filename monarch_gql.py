"""Raw GraphQL operations the monarchmoney library doesn't wrap.

These are the same operations Monarch's web app sends (taken from its JS
bundle). They are unofficial: Monarch can change them without notice.
"""

from typing import Any, Dict, Optional

from gql import gql  # installed with monarchmoney

PAYLOAD_ERRORS = """
    fragment PayloadErrorFields on PayloadError {
        fieldErrors { field messages __typename }
        message
        code
        __typename
    }
"""


def raise_payload_errors(errors: Optional[Dict[str, Any]], action: str) -> None:
    """Monarch returns an `errors` object on success too, with empty fields."""
    if not errors:
        return
    if errors.get("message"):
        raise RuntimeError(f"{action} failed: {errors['message']}")
    field_errors = errors.get("fieldErrors") or []
    if field_errors:
        detail = "; ".join(f"{fe['field']}: {', '.join(fe['messages'])}" for fe in field_errors)
        raise RuntimeError(f"{action} failed: {detail}")


# ---------------------------------------------------------------------------
# Transaction rules
# ---------------------------------------------------------------------------
GET_RULES = gql("""
    query GetTransactionRules {
        transactionRules {
            id
            order
            merchantCriteriaUseOriginalStatement
            merchantCriteria { operator value __typename }
            amountCriteria {
                operator isExpense value
                valueRange { lower upper __typename }
                __typename
            }
            categoryIds
            accountIds
            categories { id name __typename }
            accounts { id displayName __typename }
            setMerchantAction { id name __typename }
            setCategoryAction { id name __typename }
            addTagsAction { id name __typename }
            setHideFromReportsAction
            reviewStatusAction
            recentApplicationCount
            lastAppliedAt
            __typename
        }
    }
""")

CREATE_RULE = gql("""
    mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
        createTransactionRuleV2(input: $input) {
            errors { ...PayloadErrorFields __typename }
            transactionRule { id __typename }
            __typename
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_RULE = gql("""
    mutation Common_DeleteTransactionRule($id: ID!) {
        deleteTransactionRule(id: $id) {
            deleted
            errors { ...PayloadErrorFields __typename }
            __typename
        }
    }
""" + PAYLOAD_ERRORS)

AMOUNT_OPERATORS = {"eq", "gt", "lt", "between"}


def build_rule_input(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Translate tool arguments into Monarch's CreateTransactionRuleInput."""
    criteria = []
    if arguments.get("merchant_contains"):
        criteria.append({"operator": "contains", "value": arguments["merchant_contains"]})
    if arguments.get("merchant_equals"):
        criteria.append({"operator": "eq", "value": arguments["merchant_equals"]})

    amount = arguments.get("amount")
    amount_criteria = None
    if amount:
        op = amount.get("operator")
        if op not in AMOUNT_OPERATORS:
            raise ValueError(f"amount.operator must be one of {sorted(AMOUNT_OPERATORS)}")
        amount_criteria = {
            "operator": op,
            "isExpense": amount.get("is_expense", True),
            "value": None,
            "valueRange": None,
        }
        if op == "between":
            if amount.get("lower") is None or amount.get("upper") is None:
                raise ValueError("amount.lower and amount.upper are required for 'between'")
            amount_criteria["valueRange"] = {"lower": amount["lower"], "upper": amount["upper"]}
        else:
            if amount.get("value") is None:
                raise ValueError("amount.value is required unless operator is 'between'")
            amount_criteria["value"] = amount["value"]

    if not criteria and not amount_criteria and not arguments.get("account_ids") \
            and not arguments.get("match_category_ids"):
        raise ValueError("A rule needs at least one condition (merchant, amount, account, or category)")
    if not arguments.get("set_category_id") and not arguments.get("set_merchant_name") \
            and not arguments.get("add_tag_ids"):
        raise ValueError("A rule needs an action: set_category_id, set_merchant_name, and/or add_tag_ids")

    return {
        "merchantCriteria": criteria or None,
        "merchantCriteriaUseOriginalStatement": bool(arguments.get("use_original_statement", False)),
        "amountCriteria": amount_criteria,
        "accountIds": arguments.get("account_ids") or None,
        "categoryIds": arguments.get("match_category_ids") or None,
        "setCategoryAction": arguments.get("set_category_id") or None,
        "setMerchantAction": arguments.get("set_merchant_name") or None,
        "addTagsAction": arguments.get("add_tag_ids") or None,
        "splitTransactionsAction": None,
        "applyToExistingTransactions": bool(arguments.get("apply_to_existing", False)),
    }


# ---------------------------------------------------------------------------
# Savings goals (Monarch's current goals system; households are migrated to it)
# ---------------------------------------------------------------------------
GOAL_TYPES = [
    "emergency_fund", "home_down_payment", "car", "vacation", "wedding", "education",
    "retirement", "savings", "pay_off_credit_card_debt", "pay_off_student_loans",
    "pay_off_car_loan", "pay_off_mortgage", "other_debt",
]

GET_SAVINGS_GOALS = gql("""
    query Common_SavingsGoals {
        migratedToSavingsGoals
        savingsGoals {
            id
            type
            name
            createdAt
            archivedAt
            status
            progress
            currentBalance
            targetDate
            targetAmount
            currentMonthActualBudgetAmount
            currentMonthPlannedContributionAmount
            plannedMonthlyContribution
            spendingTotal
            netContribution
            balanceThisMonth
            estimatedMonthsUntilCompletion
            forecastedCompletionDate
            isSinkingFund
            priority
            allocationAmountsByAccount {
                totalAmount
                contributionsAmount
                withdrawalsAmount
                spendingAmount
                adjustmentAmount
                account { id displayName displayBalance }
            }
        }
    }
""")

CREATE_SAVINGS_GOALS = gql("""
    mutation Common_CreateSavingsGoals($input: CreateSavingsGoalsInput!) {
        createSavingsGoals(input: $input) {
            savingsGoals { id type name targetAmount targetDate priority }
        }
    }
""")

UPDATE_SAVINGS_GOAL = gql("""
    mutation Common_UpdateSavingsGoal($input: UpdateSavingsGoalInput!) {
        updateSavingsGoal(input: $input) {
            savingsGoal {
                id
                name
                type
                priority
                targetAmount
                targetDate
                plannedMonthlyContribution
                status
                isSinkingFund
                progress
                forecastedCompletionDate
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_SAVINGS_GOAL = gql("""
    mutation Common_DeleteSavingsGoal($input: DeleteSavingsGoalInput!) {
        deleteSavingsGoal(input: $input) {
            success
            errors { message }
        }
    }
""")

ARCHIVE_SAVINGS_GOAL = gql("""
    mutation Common_ArchiveSavingsGoal($input: ArchiveSavingsGoalInput!) {
        archiveSavingsGoal(input: $input) {
            savingsGoal { id archivedAt status }
            errors { message }
        }
    }
""")

UNARCHIVE_SAVINGS_GOAL = gql("""
    mutation Common_UnarchiveSavingsGoal($input: UnarchiveSavingsGoalInput!) {
        unarchiveSavingsGoal(input: $input) {
            savingsGoal { id archivedAt status }
            errors { message }
        }
    }
""")

CONTRIBUTE_TO_SAVINGS_GOAL = gql("""
    mutation Common_ContributeToSavingsGoal($input: CreateSavingsGoalContributionInput!) {
        createSavingsGoalContribution(input: $input) {
            userNotice
            goalEvent {
                id
                goal { id currentBalance progress status }
                account { id availableBalanceForGoalsUnmemoized }
            }
        }
    }
""")

WITHDRAW_FROM_SAVINGS_GOAL = gql("""
    mutation Common_WithdrawFromSavingsGoal($input: CreateSavingsGoalWithdrawalInput!) {
        createSavingsGoalWithdrawal(input: $input) {
            goalEvent {
                id
                goal { id currentBalance progress status }
                account { id availableBalanceForGoalsUnmemoized }
            }
        }
    }
""")

SET_SAVINGS_GOAL_BUDGET_AMOUNT = gql("""
    mutation Common_SetSavingsGoalBudgetAmount($input: SetSavingsGoalBudgetAmountInput!) {
        setSavingsGoalBudgetAmount(input: $input) {
            success
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)


# ---------------------------------------------------------------------------
# Merchants
# ---------------------------------------------------------------------------
MERCHANT_ORDERINGS = ["TRANSACTION_COUNT", "NAME"]
RECURRENCE_FREQUENCIES = [
    "weekly", "biweekly", "four_weekly", "semimonthly_start_mid", "semimonthly_mid_end",
    "monthly", "bimonthly", "quarterly", "four_month", "semiyearly", "yearly",
]

GET_MERCHANTS = gql("""
    query Web_GetMerchantSettingsPage(
        $offset: Int
        $limit: Int
        $orderBy: MerchantOrdering
        $search: String
    ) {
        merchants(offset: $offset, limit: $limit, orderBy: $orderBy, search: $search) {
            id
            name
            transactionCount
            createdAt
            recurringTransactionStream { id }
            defaultCategory { id name }
        }
        merchantCount
    }
""")

GET_MERCHANT = gql("""
    query Common_GetEditMerchant($merchantId: ID!) {
        merchant(id: $merchantId) {
            id
            name
            transactionCount
            ruleCount
            canBeDeleted
            hasActiveRecurringStreams
            recurrenceIgnoredAt
            defaultCategoryApplicationMode
            defaultCategory { id name }
            recurringTransactionStream { id frequency amount baseDate isActive }
        }
    }
""")

UPDATE_MERCHANT = gql("""
    mutation Common_UpdateMerchant($input: UpdateMerchantInput!) {
        updateMerchant(input: $input) {
            merchant {
                id
                name
                transactionCount
                defaultCategoryApplicationMode
                defaultCategory { id name }
                recurringTransactionStream { id frequency amount baseDate isActive }
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_MERCHANT = gql("""
    mutation Common_DeleteMerchant($merchantId: ID!, $moveToId: ID) {
        deleteMerchant(id: $merchantId, moveRelationsToMerchantId: $moveToId) {
            success
        }
    }
""")
