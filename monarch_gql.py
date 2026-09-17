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
