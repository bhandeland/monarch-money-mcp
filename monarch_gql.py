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


# ---------------------------------------------------------------------------
# Assets and restore
# ---------------------------------------------------------------------------
GET_ZESTIMATES = gql("""
    query Web_GetZestimate($address: String!, $limit: Int) {
        zestimates(address: $address, limit: $limit) {
            zpid
            addressStreet
            addressCity
            addressStateAbbr
            addressPostalCode
            zestimate
        }
    }
""")

SEARCH_VEHICLES = gql("""
    query VehiclesSearch($search: String!, $limit: Int) {
        vehicles(search: $search, limit: $limit) {
            vin
            name
            value
        }
    }
""")

# The web app's institution settings list deleted accounts this way.
GET_ACCOUNTS_INCLUDING_DELETED = gql("""
    query Web_GetDeletedAccounts {
        accounts(filters: {includeDeleted: true, includeHidden: true}) {
            id
            displayName
            deletedAt
            dataProvider
            isManual
            displayBalance
            type { name display }
            subtype { name display }
            institution { id name }
        }
    }
""")

CREATE_REAL_ESTATE_ACCOUNT = gql("""
    mutation Web_CreateZillowAccount($input: CreateSyncedRealEstateAccountInput!) {
        createSyncedRealEstateAccount(input: $input) {
            account { id }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

CREATE_VEHICLE_ACCOUNT = gql("""
    mutation CreateSyncedVehicleAccount($input: CreateSyncedVehicleAccountInput!) {
        createSyncedVehicleAccount(input: $input) {
            account { id }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

UNDELETE_ACCOUNT = gql("""
    mutation Common_UndeleteAccount($input: UndeleteAccountMutationInput!) {
        undeleteAccount(input: $input) {
            undeleted
# --- Reports ---------------------------------------------------------------

REPORT_CONFIGURATION_FIELDS = """
    fragment ReportConfigurationFields on ReportConfiguration {
        id
        displayName
        transactionFilterSet {
            id
            categories { id name }
            categoryGroups { id name type }
            accounts { id displayName }
            merchants { id name }
            tags { id name }
            isUntagged
            searchQuery
            categoryType
            isUncategorized
            budgetVariability
            isFlexSpending
            startDate
            endDate
            timeframePeriod { unit value includeCurrent }
            absAmountGte
            absAmountLte
            isSplit
            isRecurring
            isInvestmentAccount
            isPending
            creditsOnly
            debitsOnly
            hasNotes
            hasAttachments
            hiddenFromReports
            needsReview
            ownershipSet { includeJointlyOwned users { id name } }
            businessEntitySet { includeUnassigned businessEntities { id name } }
        }
        reportView {
            analysisScope
            chartType
            chartCalculation
            chartLayout
            chartDensity
            dimensions
            timeframe
        }
    }
"""

GET_REPORTS_DATA = gql("""
    query Common_GetReportsData(
        $filters: TransactionFilterInput!
        $groupBy: [ReportsGroupByEntity!]
        $groupByTimeframe: ReportsGroupByTimeframe
        $sortBy: ReportsSortBy
        $includeCategory: Boolean = false
        $includeCategoryGroup: Boolean = false
        $includeMerchant: Boolean = false
        $includeBusinessEntity: Boolean = false
        $includeBudgetVariability: Boolean = false
        $includeOwner: Boolean = false
        $fillEmptyValues: Boolean = true
    ) {
        reports(
            groupBy: $groupBy
            groupByTimeframe: $groupByTimeframe
            filters: $filters
            sortBy: $sortBy
            fillEmptyValues: $fillEmptyValues
        ) {
            groupBy {
                date
                category @include(if: $includeCategory) { id name group { id name type } }
                categoryGroup @include(if: $includeCategoryGroup) { id name type }
                merchant @include(if: $includeMerchant) { id name }
                businessEntity @include(if: $includeBusinessEntity) { id name }
                budgetVariability @include(if: $includeBudgetVariability) { id name }
                owner @include(if: $includeOwner) { id name displayName }
            }
            summary { ...ReportsSummaryFields }
        }
        aggregates(filters: $filters, fillEmptyValues: $fillEmptyValues) {
            summary { ...ReportsSummaryFields }
        }
    }

# Business entities and Schedule C
# ---------------------------------------------------------------------------
BUSINESS_ENTITY_STRUCTURES = [
    "sole_proprietorship", "llc", "llp", "lp", "partnership", "s_corp", "c_corp",
    "nonprofit", "trust", "estate", "other",
]
SCHEDULE_C_LINE_ITEMS = [
    "line_1_gross_receipts", "line_2_returns_allowances", "line_3_net_part_i",
    "line_4_cost_of_goods", "line_5_gross_profit", "line_6_other_income",
    "line_8_advertising", "line_9_car_truck", "line_10_commissions_fees",
    "line_11_contract_labor", "line_12_depletion", "line_13_depreciation",
    "line_14_employee_benefits", "line_15_insurance", "line_16a_mortgage_interest",
    "line_16b_other_interest", "line_17_legal_professional", "line_18_office_expense",
    "line_19_pension_profit_sharing", "line_20a_rent_vehicles_equipment",
    "line_20b_rent_other_property", "line_21_repairs_maintenance", "line_22_supplies",
    "line_23_taxes_licenses", "line_24a_travel", "line_24b_meals", "line_25_utilities",
    "line_26_wages", "line_27a_energy_efficient", "line_27b_other_expenses",
]

BUSINESS_ENTITY_FIELDS = """
    fragment BusinessEntityFields on BusinessEntity {
        id
        name
        description
        logoUrl
        color
        notes
        structure
        createdAt
        updatedAt
        accounts { id logoUrl displayName }
        accountsCount
        transactionsCount
    }
"""

REPORTS_SUMMARY_FIELDS = """
    fragment ReportsSummaryFields on TransactionsSummary {
        sum
        avg
        count
        max
        sumIncome
        sumExpense
        savings
        savingsRate
        first
        last
    }
""")

GET_REPORT_CONFIGURATIONS = gql("""
    query Common_GetReportConfigurations {
        reportConfigurations { ...ReportConfigurationFields }
    }
""" + REPORT_CONFIGURATION_FIELDS)

CREATE_REPORT_CONFIGURATION = gql("""
    mutation Common_CreateReportConfiguration($input: CreateReportConfigurationInput!) {
        createReportConfiguration(input: $input) {
            reportConfiguration { ...ReportConfigurationFields }
            errors { ...PayloadErrorFields }
        }
    }
""" + REPORT_CONFIGURATION_FIELDS + PAYLOAD_ERRORS)

UPDATE_REPORT_CONFIGURATION = gql("""
    mutation Common_UpdateReportConfiguration($input: UpdateReportConfigurationInput!) {
        updateReportConfiguration(input: $input) {
            reportConfiguration { ...ReportConfigurationFields }
            errors { ...PayloadErrorFields }
        }
    }
""" + REPORT_CONFIGURATION_FIELDS + PAYLOAD_ERRORS)

DELETE_REPORT_CONFIGURATION = gql("""
    mutation Common_DeleteReportConfiguration($id: ID!) {
        deleteReportConfiguration(id: $id) {
# Insights and recap
# ---------------------------------------------------------------------------
INSIGHT_LIFECYCLE_STATUSES = ["new", "in_progress", "accepted", "completed", "denied",
                              "archived", "reopened", "no_longer_applicable"]
FINANCIAL_INSIGHT_STATUSES = ["new", "in_progress", "accepted", "completed", "denied",
                              "archived", "reopened", "failed"]
OPPORTUNITY_TYPES = [
    "annual_billing", "bundle", "competitor_switch", "duplicate", "expired_promo",
    "marketplace_review", "new_subscription", "other", "plan_optimization", "product_review",
    "retention_deal", "tier_downgrade", "transfer_review", "vendor_switch", "yearly_subscription",
]

INSIGHT_FIELDS = """
    fragment InsightFields on InsightType {
        id
        insightType
        status
        isBookmarked
        feedback
        feedbackReason
        prompt
        ctaLabel
        ctaDeepLink
        title { text entityType entityId }
        body { text entityType entityId }
        contextLine { text entityType entityId }
        value
        valueCaptured
        valuePeriod
        refreshedAt
        updatedAt
        merchant { id name }
    }
"""

GET_INSIGHTS = gql("""
    query Common_GetInsights(
        $statuses: [InsightLifecycleStatusEnum!]
        $bookmarked: Boolean
        $dismissed: Boolean
        $unhelpful: Boolean
        $limit: Int
        $offset: Int
    ) {
        insights(
            statuses: $statuses
            bookmarked: $bookmarked
            dismissed: $dismissed
            unhelpful: $unhelpful
            limit: $limit
            offset: $offset
        ) {
            ...InsightFields
        }
    }
""" + INSIGHT_FIELDS)

GET_INSIGHT = gql("""
    query Common_GetInsight($id: ID!) {
        insight(id: $id) {
            ...InsightFields
        }
    }
""" + INSIGHT_FIELDS)

GET_INSIGHT_COUNTS = gql("""
    query Common_GetInsightCounts {
        insightCounts {
            completed
            bookmarked
            dismissed
            unhelpful
        }
        insightSurfacedValueTotal
    }
""")

UPDATE_INSIGHT_STATUS = gql("""
    mutation Common_UpdateInsightStatus($input: UpdateInsightStatusInput!) {
        updateInsightStatus(input: $input) {
            insight { id status }
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

SET_INSIGHT_BOOKMARKED = gql("""
    mutation Common_SetInsightBookmarked($input: SetInsightBookmarkedInput!) {
        setInsightBookmarked(input: $input) {
            insight { id isBookmarked }
UPDATE_HOLDING = gql("""
    mutation Common_UpdateHolding($input: UpdateHoldingInput!) {
        updateHolding(input: $input) {
            holding { id }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

SET_INSIGHT_FEEDBACK = gql("""
    mutation Common_SetInsightFeedback($input: SetInsightFeedbackInput!) {
        setInsightFeedback(input: $input) {
            insight { id feedback feedbackReason }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

SOFT_DELETE_INSIGHT = gql("""
    mutation Common_SoftDeleteInsight($input: SoftDeleteInsightInput!) {
        softDeleteInsight(input: $input) {
DELETE_HOLDING = gql("""
    mutation Common_DeleteHolding($id: ID!) {
        deleteHolding(id: $id) {
"""

GET_BUSINESS_ENTITIES = gql("""
    query Common_GetBusinessEntities {
        businessEntities { ...BusinessEntityFields }
    }
""" + BUSINESS_ENTITY_FIELDS)

GET_BUSINESS_ENTITIES_SUMMARY = gql("""
    query Common_GetBusinessEntitiesSummary {
        businessEntities { id name logoUrl color }
    }
""")

GET_BUSINESS_ENTITY = gql("""
    query Common_GetBusinessEntity($id: ID!) {
        businessEntity(id: $id) { ...BusinessEntityFields }
    }
""" + BUSINESS_ENTITY_FIELDS)

GET_BUSINESS_ENTITY_FINANCIALS = gql("""
    query Common_GetBusinessEntityFinancials($entityIds: [ID!]!, $startDate: Date!, $endDate: Date!) {
        businessEntityFinancials(entityIds: $entityIds, startDate: $startDate, endDate: $endDate) {
            entityId
            sumIncome
            sumExpense
            netAssets
            monthlyBreakdown { month sumIncome sumExpense }
            monthlyNetAssets { month netAssets }
        }
    }
""")

# The web app only asks for businessEntitySummaries as part of the by-category
# report below; this is that part on its own.
GET_BUSINESS_ENTITY_SUMMARIES = gql("""
    query Common_GetBusinessEntitySummaries($filters: TransactionFilterInput!) {
        businessEntitySummaries(filters: $filters) {
            businessEntity { id name color logoUrl }
            summary { ...ReportsSummaryFields }
        }
    }
""" + REPORTS_SUMMARY_FIELDS)

GET_BUSINESS_ENTITY_REPORT_BY_CATEGORY = gql("""
    query Common_GetBusinessEntityReportsDataByCategory($filters: TransactionFilterInput!) {
        reports(groupBy: [business_entity, category], filters: $filters, fillEmptyValues: false) {
            groupBy {
                businessEntity { id name color logoUrl }
                category {
                    id
                    name
                    icon
                    group { id name type }
                }
            }
            summary { ...ReportsSummaryFields }
        }
        businessEntitySummaries(filters: $filters) {
            businessEntity { id name color logoUrl }
            summary { ...ReportsSummaryFields }
        }
        aggregates(filters: $filters, fillEmptyValues: false) {
            summary { ...ReportsSummaryFields }
        }
    }
""" + REPORTS_SUMMARY_FIELDS)

UPSERT_BUSINESS_ENTITY = gql("""
    mutation Common_UpsertBusinessEntity($input: UpsertBusinessEntityInput!) {
        upsertBusinessEntity(input: $input) {
            businessEntity { ...BusinessEntityFields }
            errors { ...PayloadErrorFields }
        }
    }
""" + BUSINESS_ENTITY_FIELDS + PAYLOAD_ERRORS)

DELETE_BUSINESS_ENTITY = gql("""
    mutation Common_DeleteBusinessEntity($id: ID!) {
        deleteBusinessEntity(id: $id) {
            deleted
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

UNDO_INSIGHT_DENIAL = gql("""
    mutation Common_UndoInsightDenial($input: UndoInsightDenialInput!) {
        undoInsightDenial(input: $input) {
            insight { id status }
CREATE_MANUAL_INVESTMENTS_ACCOUNT = gql("""
    mutation Common_CreateManualInvestmentsAccount($input: CreateManualInvestmentsAccountInput!) {
        createManualInvestmentsAccount(input: $input) {
            account { id }
UPDATE_ACCOUNTS_BUSINESS_ENTITY = gql("""
    mutation Common_UpdateAccountsForEditingEntities($input: [UpdateAccountsMutationInput!]!) {
        updateAccounts(input: $input) {
            accounts {
                id
                displayName
                businessEntity { id name }
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

FINANCIAL_INSIGHT_FIELDS = """
    fragment FinancialInsightFields on FinancialInsightType {
        id
        merchantNameDisplay
        productNameDisplay
        dashboardSubtitle
        description
        reasoning
        effort
        status
        opportunityType
        suggestedActionType
        executionMethod
        savingsEstimateLow
        savingsEstimateHigh
        capturedSavingsLow
        currentAnnualCost
        nextChargeDate
        score
        relatedMerchants { name merchantId }
    }
"""

GET_FINANCIAL_INSIGHTS = gql("""
    query Common_GetFinancialInsightsList(
        $statuses: [InsightStatusEnum!]
        $opportunityTypes: [OpportunityTypeEnum!]
        $limit: Int
        $offset: Int
    ) {
        financialInsights(
            statuses: $statuses
            opportunityTypes: $opportunityTypes
            limit: $limit
            offset: $offset
        ) {
            ...FinancialInsightFields
        }
    }
""" + FINANCIAL_INSIGHT_FIELDS)

GET_FINANCIAL_INSIGHT = gql("""
    query Common_GetFinancialInsight($id: ID!) {
        financialInsight(id: $id) {
            ...FinancialInsightFields
            recurringStreamSnapshot
            paymentAccount { label }
            actions {
                id
                order
                suggestedActionType
                productName
                merchantPlaybook { id diySteps }
            }
        }
    }
""" + FINANCIAL_INSIGHT_FIELDS)

GET_FINANCIAL_INSIGHT_SUMMARY = gql("""
    query Common_GetFinancialInsightSummary($startDate: Date, $endDate: Date) {
        financialInsightSummary(startDate: $startDate, endDate: $endDate) {
            totalCapturedSavings
            totalIdentifiedSavingsLow
            totalIdentifiedSavingsHigh
            newCount
            inProgressCount
            acceptedCount
            completedCount
        }
        latestFinancialInsightRun {
            id
            status
            trigger
            createdAt
            completedAt
            errorMessage
            insightsGeneratedCount
            totalInsightsCount
SET_HOLDING_CLASSIFICATION = gql("""
    mutation Web_SetHoldingClassification($input: SetHoldingClassificationInput!) {
        setHoldingClassification(input: $input) {
            holdingClassification {
                id
""" + CLASSIFICATION_SLICES + """
            }
            errors { message }
GET_SCHEDULE_C_LINE_ITEMS = gql("""
    query Web_GetScheduleCLineItems($taxYear: Int!) {
        scheduleCLineItems(taxYear: $taxYear) {
            key
            lineNumber
            description
            lineType
            sortOrder
            isNotTracked
            displayInfo
        }
    }
""")

UPDATE_FINANCIAL_INSIGHT_STATUS = gql("""
    mutation Common_UpdateFinancialInsightStatus($input: UpdateFinancialInsightStatusInput!) {
        updateFinancialInsightStatus(input: $input) {
            financialInsight { id status executionMethod }
GET_TAX_SCHEDULE_CATEGORY_MAPPINGS = gql("""
    query Web_GetTaxScheduleCategoryMappings($schedule: TaxSchedule!, $taxYear: Int!) {
        taxScheduleCategoryMappings(schedule: $schedule, taxYear: $taxYear) {
            id
            lineItem
            schedule
            taxYear
            category { id name icon }
            lineItemInfo { key lineNumber description lineType sortOrder }
        }
    }
""")

ASSIGN_TAX_SCHEDULE_CATEGORY_MAPPING = gql("""
    mutation Web_AssignTaxScheduleCategoryMapping($input: AssignTaxScheduleCategoryMappingInput!) {
        assignTaxScheduleCategoryMapping(input: $input) {
            taxScheduleCategoryMapping {
                id
                lineItem
                schedule
                taxYear
                category { id name }
                lineItemInfo { key lineNumber description lineType sortOrder }
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)

GET_WEEKLY_RECAP = gql("""
    query Common_GetWeeklyRecap($startDate: Date!, $endDate: Date!) {
        recap(startDate: $startDate, endDate: $endDate) {
            id
            dateRangeStart
            dateRangeEnd
            summary
            sentiment
            createdAt
            updatedAt
            cards {
                module
                title
                headline
                message
                sentiment
                metrics
            }
SET_SECURITY_CLASSIFICATION = gql("""
    mutation Web_SetSecurityClassification($input: SetSecurityClassificationInput!) {
        setSecurityClassification(input: $input) {
            securityClassification {
                id
""" + CLASSIFICATION_SLICES + """
            }
            errors { message }
# Forecasting and paychecks
# ---------------------------------------------------------------------------
DEBT_PAYDOWN_METHODS = ["avalanche", "snowball", "planned"]
FORECAST_DOLLAR_MODES = ["todaysDollars", "futureDollars"]
PAYROLL_PROVIDERS = [
    "adp", "bamboohr", "cloudpay", "deel", "gusto", "homebase", "insperity", "justworks",
    "onpay", "other", "papaya_global", "patriot", "paychex", "paycom", "paycor", "paylocity",
    "quickbooks", "remote", "rippling", "square", "surepayroll", "trinet", "ukg",
    "velocity_global", "wave", "zenefits",
]
PAYCHECK_DEDUCTION_TYPES = [
    "federal_income_tax", "state_income_tax", "city_income_tax", "social_security_tax",
    "medicare_tax", "state_disability_insurance", "traditional_401k", "roth_401k",
    "loan_repayment_401k", "plan_403b", "plan_457b", "mandatory_public_retirement", "espp",
    "medical_insurance", "dental_insurance", "vision_insurance", "life_insurance",
    "group_term_life", "disability_insurance", "hsa_payroll", "healthcare_fsa",
    "dependent_care_fsa", "transit_pass", "union_dues", "charitable_contributions",
    "child_support", "creditor_garnishment", "student_loan_garnishment", "tax_levy",
    "company_reimbursement", "salary_advance_repayment", "custom",
]

GET_CASH_FLOW_PROJECTION = gql("""
    query Common_GetCashFlowProjection(
        $accountId: ID!
        $startDate: Date
        $endDate: Date
        $days: Int
    ) {
        cashFlowProjection(
            accountId: $accountId
            startDate: $startDate
            endDate: $endDate
            days: $days
        ) {
            account { id displayName displayBalance isAsset targetThreshold effectiveThreshold }
            startDate
            endDate
            startingBalance
            dailyBalances { date startingBalance endingBalance balance netChange isOverdraft }
            virtualTransactions {
                id
                date
                amount
                description
                isRecurring
                confidence
                streamType
                merchant { id name }
                category { id name }
            }
            overdraftDates
            lowestBalance
            lowestBalanceDate
            safeToSpend
# Budget moves and flex
# ---------------------------------------------------------------------------
GET_BUDGET_SETTINGS = gql("""
    query Common_GetBudgetSettings {
        budgetSystem
        budgetApplyToFutureMonthsDefault
        flexExpenseRolloverPeriod {
            id
            startMonth
            endMonth
            startingBalance
            targetAmount
            frequency
            type
        }
        budgetStatus {
            hasBudget
            hasTransactions
            willCreateBudgetFromEmptyDefaultCategories
        }
    }
""")

FORECAST_SCENARIO_LIST_ITEM = """
    fragment ForecastScenarioListItemFields on ForecastScenarioListItemType {
        externalId
        name
        icon
        color
        order
        kpis
    }
"""

FORECAST_CATEGORY_VERSIONS = """
    fragment ForecastCategoryVersionsAllFields on ForecastCategoryVersionsType {
        settingsVersion
        eventsVersion
        accountsVersion
        participantsVersion
        priorityRulesVersion
    }
"""

FORECAST_SCENARIO = """
    fragment ForecastScenarioFields on ForecastScenarioType {
        externalId
        name
        icon
        color
        inflationRate
        projectionYears
        useActualsAsBaseline
        splitUncategorizedSavings
        dollarMode
        monteCarloEnabled
        accounts {
            externalId
            monarchAccountId
            name
            signedBalance
            accountType
            accountSubtype
            isSynthetic
            isIncluded
            growthRate
            growthRateMethod
            interestRate
            plannedPayment
            minimumPayment
            withdrawalTaxRate
            withdrawalStartingYear
            yearlyPaycheckContribution
            ownerUserId
        }
        participants {
            user { id displayName birthday }
            lifeExpectancy
            isIncluded
        }
        events {
            externalId
            eventKind
            name
            startYear
            isIncluded
            isHidden
            isRequired
            config
        }
        priorityRules { accountExternalId componentKind ruleType order config }
        categoryVersions { ...ForecastCategoryVersionsAllFields }
        baselineIncome
        baselineExpenses
        compareToScenarioExternalId
    }
""" + FORECAST_CATEGORY_VERSIONS

GET_FORECAST_SCENARIOS = gql("""
    query Web_ForecastScenarios {
        forecastScenarios {
            ...ForecastScenarioListItemFields
        }
    }
""" + FORECAST_SCENARIO_LIST_ITEM)

GET_FORECAST_SCENARIO = gql("""
    query Web_ForecastScenario($externalId: ID) {
        forecastScenario(externalId: $externalId) {
            ...ForecastScenarioFields
        }
    }
""" + FORECAST_SCENARIO)

# updateForecastScenario needs the scenario's current settings version.
GET_FORECAST_SCENARIO_SETTINGS_VERSION = gql("""
    query Common_ForecastScenarioSettingsVersion($externalId: ID) {
        forecastScenario(externalId: $externalId) {
            externalId
            categoryVersions { settingsVersion }
        }
    }
""")

CREATE_FORECAST_SCENARIO = gql("""
    mutation Web_CreateForecastScenario($input: CreateForecastScenarioInput!) {
        createForecastScenario(input: $input) {
            scenario {
                ...ForecastScenarioFields
            }
            errors {
                message
            }
        }
    }
""" + FORECAST_SCENARIO)

UPDATE_FORECAST_SCENARIO = gql("""
    mutation Web_UpdateForecastScenario($input: UpdateForecastScenarioInput!) {
        updateForecastScenario(input: $input) {
            newVersion
            scenario {
                externalId
                name
                icon
                color
                inflationRate
                projectionYears
                useActualsAsBaseline
                splitUncategorizedSavings
                dollarMode
                categoryVersions { ...ForecastCategoryVersionsAllFields }
            }
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + FORECAST_CATEGORY_VERSIONS + PAYLOAD_ERRORS)

DUPLICATE_FORECAST_SCENARIO = gql("""
    mutation Web_DuplicateForecastScenario($input: DuplicateForecastScenarioInput!) {
        duplicateForecastScenario(input: $input) {
            scenario {
                ...ForecastScenarioFields
            }
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + FORECAST_SCENARIO + PAYLOAD_ERRORS)

DELETE_FORECAST_SCENARIO = gql("""
    mutation Web_DeleteForecastScenario($input: DeleteForecastScenarioInput!) {
        deleteForecastScenario(input: $input) {
            deleted
            deletedScenarioExternalId
            errors {
                ...PayloadErrorFields
            }
            scenarios {
                ...ForecastScenarioListItemFields
            }
        }
    }
""" + FORECAST_SCENARIO_LIST_ITEM + PAYLOAD_ERRORS)

DEBT_ACCOUNT = """
    fragment DebtAccountFields on Account {
        id
        displayName
        displayBalance
        includeInNetWorth
        isHidden
        displayLastUpdatedAt
        apr
        interestRate
        minimumPayment
        plannedPayment
        excludeFromDebtPaydown
        type { name display }
        subtype { name display }
    }
"""

GET_DEBT_ACCOUNTS = gql("""
    query Common_DebtPaydownAccounts {
        debtAccounts {
            id
            ...DebtAccountFields
        }
    }
""" + DEBT_ACCOUNT)

GET_DEBT_PAYDOWN_PLAN = gql("""
    query Common_DebtPaydown($input: SavingsCalculatorInput!) {
        debtAccounts {
            id
            ...DebtAccountFields
        }
        debtProjectionForecastLimit
        debtPaydownPlan(input: $input) {
            currentDebtPrincipal
            projectedInterest
            adjustedProjectedInterest
            projectedTotal
            adjustedProjectedTotal
            debtFreeDate
            adjustedDebtFreeDate
            debtAccountProjections {
                account { id displayName }
                principal
                projectedInterest
                projectedTotal
                debtFreeDate
            }
        }
    }
""" + DEBT_ACCOUNT)

GET_DEBT_PAYDOWN_BUDGET_AMOUNTS = gql("""
    query Common_DebtPaydownMonthlyBudgetAmounts($startMonth: Date!, $endMonth: Date!) {
        debtPaydownMonthlyBudgetAmounts(startMonth: $startMonth, endMonth: $endMonth) {
            id
            account { id displayName displayBalance }
            monthlyAmounts { id month plannedAmount actualAmount remainingAmount }
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
DELETE_TAX_SCHEDULE_CATEGORY_MAPPING = gql("""
    mutation Web_DeleteTaxScheduleCategoryMapping($input: DeleteTaxScheduleCategoryMappingInput!) {
        deleteTaxScheduleCategoryMapping(input: $input) {
            deleted
MOVE_BUDGET_MONEY = gql("""
    mutation Web_MoveMoneyMutation($input: MoveMoneyMutationInput!) {
        moveMoneyBetweenCategories(input: $input) {
            fromBudgetItem { id budgetAmount }
            toBudgetItem { id budgetAmount }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)
SET_DEBT_PAYDOWN_BUDGET_AMOUNT = gql("""
    mutation Common_SetDebtPaydownBudgetAmount($input: SetDebtPaydownBudgetAmountInput!) {
        setDebtPaydownBudgetAmount(input: $input) {
            success
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + PAYLOAD_ERRORS)

PAYCHECK = """
    fragment PaycheckFields on Paycheck {
        id
        employer { id name }
        employerName
        payrollProvider
        payDate
        payPeriodStart
        payPeriodEnd
        grossAmount
        createdAt
        isMagicImported
        owner { id name }
        createdBy { id name }
        deductions { id deductionType customDeductionName amount }
        deposits {
            id
            transaction {
                id
                amount
                date
                merchant { id name }
                account { id displayName }
            }
        }
    }
"""

GET_PAYCHECKS = gql("""
    query Common_GetPaychecks($startDate: Date, $endDate: Date, $ownerId: ID, $employerId: ID) {
        paychecks(
            startDate: $startDate
            endDate: $endDate
            ownerId: $ownerId
            employerId: $employerId
        ) {
            ...PaycheckFields
        }
    }
""" + PAYCHECK)

GET_PAYCHECK = gql("""
    query Common_GetPaycheck($id: ID!) {
        paycheck(id: $id) {
            ...PaycheckFields
        }
    }
""" + PAYCHECK)

GET_PAYCHECKS_SUMMARY = gql("""
    query Common_GetPaychecksSummary(
        $startDate: Date
        $endDate: Date
        $ownerIds: [ID!]
        $employerId: ID
    ) {
        paychecksSummary(
            startDate: $startDate
            endDate: $endDate
            ownerIds: $ownerIds
            employerId: $employerId
        ) {
            count
            totalGross
            totalDeductions
            totalNet
            deductionRate
            deductionsByType { deductionType totalAmount }
        }
    }
""")

GET_PAYCHECK_EMPLOYERS = gql("""
    query Common_GetPaycheckEmployers($search: String, $limit: Int, $offset: Int) {
        paycheckEmployers(search: $search, limit: $limit, offset: $offset) {
            id name paycheckCount createdAt
        }
        paycheckEmployerCount
    }
""")

CREATE_PAYCHECK = gql("""
    mutation Common_CreatePaycheck($input: CreatePaycheckInput!) {
        createPaycheck(input: $input) {
            paycheck {
                ...PaycheckFields
            }
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + PAYCHECK + PAYLOAD_ERRORS)

UPDATE_PAYCHECK = gql("""
    mutation Common_UpdatePaycheck($input: UpdatePaycheckInput!) {
        updatePaycheck(input: $input) {
            paycheck {
                ...PaycheckFields
            }
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + PAYCHECK + PAYLOAD_ERRORS)

DELETE_PAYCHECK = gql("""
    mutation Common_DeletePaycheck($input: DeletePaycheckInput!) {
        deletePaycheck(input: $input) {
            success
            errors {
                ...PayloadErrorFields
            }
        }
    }
""" + PAYLOAD_ERRORS)

CREATE_PAYCHECK_EMPLOYER = gql("""
    mutation Common_CreatePaycheckEmployer($input: CreatePaycheckEmployerInput!) {
        createPaycheckEmployer(input: $input) {
            employer { id name paycheckCount createdAt }
            errors { message }
        }
    }
""")

UPDATE_PAYCHECK_EMPLOYER = gql("""
    mutation Common_UpdatePaycheckEmployer($input: UpdatePaycheckEmployerInput!) {
        updatePaycheckEmployer(input: $input) {
            employer { id name paycheckCount createdAt }
            errors { message }
        }
    }
""")

DELETE_PAYCHECK_EMPLOYER = gql("""
    mutation Common_DeletePaycheckEmployer($id: ID!) {
        deletePaycheckEmployer(id: $id) {
            success
            errors { message }
        }
    }
""")

UPDATE_BUDGET_SETTINGS = gql("""
    mutation Common_UpdateBudgetSettings($input: UpdateBudgetSettingsMutationInput!) {
        updateBudgetSettings(input: $input) {
            budgetSystem
            budgetApplyToFutureMonthsDefault
            budgetRolloverPeriod {
                id
                startMonth
                startingBalance
            }
        }
    }
""")

RESET_BUDGET_ROLLOVER = gql("""
    mutation Web_ResetRolloverMutation($input: ResetBudgetRolloverInput!) {
        resetBudgetRollover(input: $input) {
            budgetRolloverPeriod {
                id
                startMonth
                endMonth
                startingBalance
                targetAmount
                frequency
                type
            }
            errors { ...PayloadErrorFields }
        }
    }
""" + PAYLOAD_ERRORS)
