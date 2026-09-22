# Hard backstop on the user's stated $20 total spend ceiling for this project.
# Two independent warnings: a FORECASTED trip at 75% gives an early heads-up
# before money is actually spent, and an ACTUAL trip at 100% confirms the cap
# was reached. Neither notification stops spending automatically (AWS Budgets
# can't do that on its own without a separate automation action, which is out
# of scope here) -- this is an alert, not a circuit breaker; docs/cost_and_cleanup.md
# tells the user to stop/destroy manually on either alert.
resource "aws_budgets_budget" "monthly_cap" {
  name         = "${local.name_prefix}-monthly-cap"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_warning_pct
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
