"""Raw GraphQL operations the monarchmoney library doesn't wrap.

These are the same operations Monarch's web app sends (taken from its JS
bundle). They are unofficial: Monarch can change them without notice.
"""

from typing import Any, cast

from gql import GraphQLRequest, gql  # installed with monarchmoney
from graphql import DocumentNode, OperationDefinitionNode
from monarchmoney import MonarchMoney

PAYLOAD_ERRORS = """
    fragment PayloadErrorFields on PayloadError {
        fieldErrors { field messages __typename }
        message
        code
        __typename
    }
"""


async def execute(mm: MonarchMoney, request: GraphQLRequest,
                  variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one of the operations below, named after its operation definition."""
    operation = request.document.definitions[0]
    assert isinstance(operation, OperationDefinitionNode) and operation.name
    # gql_call is annotated as taking a DocumentNode, but with gql 4 (which we
    # use) the library passes it through as a GraphQLRequest.
    return await mm.gql_call(operation=operation.name.value,
                             graphql_query=cast(DocumentNode, request),
                             variables=variables or {})


def raise_payload_errors(errors: dict[str, Any] | None, action: str) -> None:
    """Monarch returns an `errors` object on success too, with empty fields."""
    if not errors:
        return
    if errors.get("message"):
        raise RuntimeError(f"{action} failed: {errors['message']}")
    field_errors = errors.get("fieldErrors") or []
    if field_errors:
        detail = "; ".join(f"{fe['field']}: {', '.join(fe['messages'])}" for fe in field_errors)
        raise RuntimeError(f"{action} failed: {detail}")


# Cheapest authenticated query; used to check that a token still works.
GET_ME = gql("""
    query Common_GetMe {
        me { id }
    }
""")


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


def build_rule_input(arguments: dict[str, Any]) -> dict[str, Any]:
    """Translate tool arguments into Monarch's CreateTransactionRuleInput."""
    criteria: list[dict[str, str]] = []
    if arguments.get("merchant_contains"):
        criteria.append({"operator": "contains", "value": arguments["merchant_contains"]})
    if arguments.get("merchant_equals"):
        criteria.append({"operator": "eq", "value": arguments["merchant_equals"]})

    amount = arguments.get("amount")
    amount_criteria: dict[str, Any] | None = None
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


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------
GET_HOUSEHOLD_MEMBERS = gql("""
    query Common_GetHouseholdMembers {
        myHousehold {
            id
            name
            users { id displayName email }
        }
    }
""")

SEMANTIC_SEARCH = gql("""
    query Web_GetCommandPaletteEntities($query: String!) {
        semanticSearch(query: $query) {
            results { id type name }
        }
    }
""")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
REVIEW_STATUSES = ["needs_review", "reviewed"]

UPDATE_TRANSACTION = gql("""
    mutation Web_TransactionDrawerUpdateTransaction($input: UpdateTransactionMutationInput!) {
        updateTransaction(input: $input) {
            transaction {
                id
                date
                amount
                notes
                hideFromReports
                needsReview
                reviewStatus
                isRecurring
                merchant { id name }
                category { id name }
                goal { id name }
                ownedByUser { id displayName }
                businessEntity { id name }
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

BULK_UPDATE_TRANSACTIONS = gql("""
    mutation Common_BulkUpdateTransactionsMutation(
        $selectedTransactionIds: [ID!]
        $excludedTransactionIds: [ID!]
        $allSelected: Boolean!
        $expectedAffectedTransactionCount: Int!
        $updates: TransactionUpdateParams!
        $filters: TransactionFilterInput
    ) {
        bulkUpdateTransactions(
            selectedTransactionIds: $selectedTransactionIds
            excludedTransactionIds: $excludedTransactionIds
            updates: $updates
            allSelected: $allSelected
            expectedAffectedTransactionCount: $expectedAffectedTransactionCount
            filters: $filters
        ) {
            success
            affectedCount
            errors { message }
        }
    }
""")

BULK_DELETE_TRANSACTIONS = gql("""
    mutation Common_BulkDeleteTransactionsMutation(
        $selectedTransactionIds: [ID!]
        $excludedTransactionIds: [ID!]
        $allSelected: Boolean!
        $expectedAffectedTransactionCount: Int!
        $filters: TransactionFilterInput
    ) {
        bulkDeleteTransactions(
            input: {
                selectedTransactionIds: $selectedTransactionIds
                excludedTransactionIds: $excludedTransactionIds
                isAllSelected: $allSelected
                expectedAffectedTransactionCount: $expectedAffectedTransactionCount
                filters: $filters
            }
        ) {
            success
            affectedCount
            errors { message }
        }
    }
""")

MOVE_TRANSACTIONS = gql("""
    mutation Web_MoveTransactions($input: MoveTransactionsInput!) {
        moveTransactions(input: $input) {
            numTransactionsMoved
            errors { message }
        }
    }
""")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
UPDATE_TRANSACTION_TAG = gql("""
    mutation Common_UpdateTransactionTag($input: UpdateTransactionTagInput!) {
        updateTransactionTag(input: $input) {
            tag { id name color order }
            errors { message }
        }
    }
""")

DELETE_TRANSACTION_TAG = gql("""
    mutation Common_DeleteHouseholdTransactionTag($tagId: ID!) {
        deleteTransactionTag(tagId: $tagId) {
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)


# ---------------------------------------------------------------------------
# Categories and category groups
# ---------------------------------------------------------------------------
CATEGORY_TYPES = ["expense", "income", "transfer"]
BUDGET_VARIABILITIES = ["fixed", "flexible", "non_monthly"]

UPDATE_CATEGORY = gql("""
    mutation Web_UpdateCategory($input: UpdateCategoryInput!) {
        updateCategory(input: $input) {
            errors { ...PayloadErrorFields }
            category {
                id
                name
                icon
                excludeFromBudget
                budgetVariability
                rolloverPeriod { id startMonth }
                group { id name type }
            }
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_CATEGORY = gql("""
    mutation Web_DeleteCategory($id: UUID!, $moveToCategoryId: UUID) {
        deleteCategory(id: $id, moveToCategoryId: $moveToCategoryId) {
            deleted
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

CATEGORY_GROUP_FIELDS = """
    fragment CategoryGroupFields on CategoryGroup {
        id
        name
        order
        type
        color
        groupLevelBudgetingEnabled
        budgetVariability
    }
"""

CREATE_CATEGORY_GROUP = gql("""
    mutation Common_CreateCategoryGroup($input: CreateCategoryGroupInput!) {
        createCategoryGroup(input: $input) {
            categoryGroup { ...CategoryGroupFields }
        }
    }
""" + CATEGORY_GROUP_FIELDS)

UPDATE_CATEGORY_GROUP = gql("""
    mutation Common_UpdateCategoryGroup($input: UpdateCategoryGroupInput!) {
        updateCategoryGroup(input: $input) {
            categoryGroup { ...CategoryGroupFields }
        }
    }
""" + CATEGORY_GROUP_FIELDS)

DELETE_CATEGORY_GROUP = gql("""
    mutation Common_DeleteCategoryGroup($id: UUID!, $moveToGroupId: UUID) {
        deleteCategoryGroup(id: $id, moveToGroupId: $moveToGroupId) {
            deleted
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)


# ---------------------------------------------------------------------------
# Rule updates and previews
# ---------------------------------------------------------------------------
UPDATE_RULE = gql("""
    mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
        updateTransactionRuleV2(input: $input) {
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

UPDATE_RULE_ORDER = gql("""
    mutation Web_UpdateRuleOrderMutation($id: ID!, $order: Int!) {
        updateTransactionRuleOrderV2(id: $id, order: $order) {
            transactionRules { id order }
        }
    }
""")

PREVIEW_RULE = gql("""
    query Common_PreviewTransactionRule($rule: TransactionRulePreviewInput!, $offset: Int) {
        transactionRulePreview(input: $rule) {
            totalCount
            results(offset: $offset, limit: 30) {
                newName
                newCategory { id name }
                newTags { id name }
                newHideFromReports
                transaction {
                    id
                    date
                    amount
                    merchant { id name }
                    category { id name }
                }
            }
        }
    }
""")


# ---------------------------------------------------------------------------
# Recurring
# ---------------------------------------------------------------------------
GET_RECURRING_STREAMS = gql("""
    query Common_GetRecurringStreams($includeLiabilities: Boolean) {
        recurringTransactionStreams(includePending: true, includeLiabilities: $includeLiabilities) {
            stream {
                id
                reviewStatus
                frequency
                amount
                baseDate
                dayOfTheMonth
                isApproximate
                name
                recurringType
                merchant { id }
            }
        }
    }
""")

MARK_STREAM_NOT_RECURRING = gql("""
    mutation Common_MarkAsNotRecurring($streamId: ID!) {
        markStreamAsNotRecurring(streamId: $streamId) {
            success
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

GET_RECURRING_REMAINING_DUE = gql("""
    query Web_GetDashboardUpcomingRecurringTransactionItems(
        $startDate: Date!
        $endDate: Date!
        $includeLiabilities: Boolean
    ) {
        recurringRemainingDue(
            startDate: $startDate
            endDate: $endDate
            includeLiabilities: $includeLiabilities
        ) {
            amount
        }
    }
""")


# --- Investments ---

CLASSIFICATION_SLICES = """
            slices {
                id
                allocationSlug
                percentage
                breakdownMode
                referenceSecurityId
                subSlices { id allocationSlug percentage breakdownMode referenceSecurityId }
            }
"""

GET_PORTFOLIO = gql("""
    query Web_GetPortfolio($portfolioInput: PortfolioInput) {
        portfolio(input: $portfolioInput) {
            performance {
                totalValue
                totalChangePercent
                totalChangeDollars
                oneDayChangePercent
                historicalChart { date returnPercent }
                benchmarks {
                    security { id ticker name oneDayChangePercent }
                    historicalChart { date returnPercent }
                }
            }
            aggregateHoldings {
                edges {
                    node {
                        id
                        quantity
                        costBasis
                        totalValue
                        securityPriceChangeDollars
                        securityPriceChangePercent
                        lastSyncedAt
                        holdings {
                            id
                            type
                            typeDisplay
                            name
                            ticker
                            closingPrice
                            closingPriceUpdatedAt
                            isManual
                            quantity
                            value
                            costBasis
                            userCostBasis
                            account { id displayName }
                            taxLots { id acquisitionDate acquisitionQuantity costBasisPerUnit }
                            securityClassification { id categorySlug }
                            holdingClassification { id categorySlug }
                        }
                        security {
                            id
                            name
                            ticker
                            currentPrice
                            currentPriceUpdatedAt
                            closingPrice
                            type
                            typeDisplay
                            assetClass
                        }
                    }
                }
            }
        }
    }
""")

SEARCH_SECURITIES = gql("""
    query SecuritySearch($search: String!, $limit: Int, $orderByPopularity: Boolean) {
        securities(search: $search, limit: $limit, orderByPopularity: $orderByPopularity) {
            id
            name
            type
            typeDisplay
            ticker
            currentPrice
            closingPrice
            oneDayChangeDollars
            oneDayChangePercent
        }
    }
""")

GET_SECURITY = gql("""
    query Common_GetSecurityDetails($id: ID!) {
        security(id: $id) {
            id
            name
            ticker
            type
            typeDisplay
            assetClass
            broadAssetClass
            exchangeCode
            currentPrice
            currentPriceUpdatedAt
            closingPrice
            closingPriceUpdatedAt
            oneDayChangeDollars
            oneDayChangePercent
            morningstarCategory
            prospectusObjective
        }
    }
""")

GET_SECURITY_PERFORMANCE = gql("""
    query Web_GetSecuritiesHistoricalPerformance($input: SecurityHistoricalPerformanceInput!) {
        securityHistoricalPerformance(input: $input) {
            security { id }
            historicalChart { date returnPercent }
        }
    }
""")

GET_SECURITY_TYPES = gql("""
    query Common_GetSecurityTypes {
        securityTypes { type typeDisplay }
    }
""")

GET_ALLOCATION_CATEGORIES = gql("""
    query Web_GetAllocationCategoriesForClassification {
        myHousehold {
            id
            allocationCategories {
                id
                slug
                name
                parent { id }
            }
        }
    }
""")

CREATE_MANUAL_HOLDING = gql("""
    mutation Common_CreateManualHolding($input: CreateManualHoldingInput!) {
        createManualHolding(input: $input) {
            holding { id ticker }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

UPDATE_HOLDING = gql("""
    mutation Common_UpdateHolding($input: UpdateHoldingInput!) {
        updateHolding(input: $input) {
            holding { id }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_HOLDING = gql("""
    mutation Common_DeleteHolding($id: ID!) {
        deleteHolding(id: $id) {
            deleted
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

CREATE_MANUAL_INVESTMENTS_ACCOUNT = gql("""
    mutation Common_CreateManualInvestmentsAccount($input: CreateManualInvestmentsAccountInput!) {
        createManualInvestmentsAccount(input: $input) {
            account { id }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

SET_HOLDING_CLASSIFICATION = gql("""
    mutation Web_SetHoldingClassification($input: SetHoldingClassificationInput!) {
        setHoldingClassification(input: $input) {
            holdingClassification {
                id
""" + CLASSIFICATION_SLICES + """
            }
            errors { message }
        }
    }
""")

SET_SECURITY_CLASSIFICATION = gql("""
    mutation Web_SetSecurityClassification($input: SetSecurityClassificationInput!) {
        setSecurityClassification(input: $input) {
            securityClassification {
                id
""" + CLASSIFICATION_SLICES + """
            }
            errors { message }
        }
    }
""")

CLEAR_HOLDING_CLASSIFICATION = gql("""
    mutation Web_ClearHoldingClassification($holdingId: ID!) {
        clearHoldingClassification(holdingId: $holdingId) {
            deleted
            errors { message }
        }
    }
""")

CLEAR_SECURITY_CLASSIFICATION = gql("""
    mutation Web_ClearSecurityClassification($securityId: ID!) {
        clearSecurityClassification(securityId: $securityId) {
            deleted
            errors { message }
        }
    }
""")
