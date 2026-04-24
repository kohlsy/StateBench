# StateBench: 10 Concrete Example Tasks

Each example shows the domain, initial policy summary, update stream, what makes it hard, and the behavioral gap the agent must close.

---

## Example 1: Refund — Easy

**Task ID:** `ex_007`  
**Domain:** refund  
**Difficulty:** easy  
**Initial rules:** 4  
**Updates:** 2

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **52.8%**

### What makes it hard

A single definition change shifts the refund window; a new rule adds high-value escalation. No interaction — each update is self-contained.

**Dominant interaction pattern:** sequential local edits

### Initial Policy Summary

**Definitions:** {"standard_window": 45, "extended_window": 60, "max_refund_amount": 1000}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`

```yaml
definitions:
  standard_window: 45
  extended_window: 60
  max_refund_amount: 1000
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: offer_store_credit
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - purchase_age_days > {standard_window}
  - purchase_channel == 'in_store'
  - is_final_sale == False
  decision: approve_refund
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - purchase_age_days < 16
  decision: deny_refund
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - purchase_age_days < {standard_window}
  - is_final_sale == True
  - customer_tier == 'silver'
  decision: approve_refund
  priority: 4
```

### Update Stream (2 updates)

1. `[add_rule]` Add new rule: update_1_new_rule
2. `[change_decision]` Change decision of 'rule_1' from approve_refund to escalate_to_manager

### What Changed (Gold vs Initial)

- Rules **added**: `update_1_new_rule`
- **52.8%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 502, wrong_decision: 26

### Counterexample (initial policy is wrong here)

```
Scenario:  {'purchase_age_days': 136, 'purchase_channel': 'in_store', 'is_final_sale': True, 'customer_tier': 'silver', 'item_condition': 'opened'}
Expected:  approve_refund (rule: update_1_new_rule)
Got (initial): offer_store_credit (rule: default_action)
```

---

## Example 2: Approval — Easy

**Task ID:** `ex_040`  
**Domain:** approval  
**Difficulty:** easy  
**Initial rules:** 4  
**Updates:** 3

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **33.8%**

### What makes it hard

A rule is revoked and another's decision flips. The tricky part: revoking the rule lets a lower-priority fallback take over cases that were previously handled.

**Dominant interaction pattern:** priority inversion, scope exposure

### Initial Policy Summary

**Definitions:** {"auto_approve_limit": 250, "manager_limit": 5000, "director_limit": 50000}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`

```yaml
definitions:
  auto_approve_limit: 250
  manager_limit: 5000
  director_limit: 50000
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: deny
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - department == 'sales'
  decision: manager_approval
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - requester_level in ['intern', 'ic']
  - expense_type in ['travel', 'software', 'hardware', 'consulting']
  decision: auto_approve
  priority: 3
  overrides:
  - rule_1
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - is_recurring == False
  - is_budgeted == True
  - amount <= 20694
  decision: manager_approval
  priority: 4
```

### Update Stream (3 updates)

1. `[narrow_scope]` Narrow scope of 'rule_3': add condition 'requester_level in ['intern', 'manager', 'director']'
2. `[change_priority]` Swap priorities: 'rule_2' (pri 3) <-> 'rule_1' (pri 2)

### What Changed (Gold vs Initial)

- **33.8%** of scenarios now produce a different decision
- Failure breakdown: wrong_decision: 338

### Counterexample (initial policy is wrong here)

```
Scenario:  {'department': 'sales', 'requester_level': 'ic', 'expense_type': 'consulting', 'is_recurring': False, 'is_budgeted': False, 'amount': 32914}
Expected:  manager_approval (rule: rule_1)
Got (initial): auto_approve (rule: rule_2)
```

---

## Example 3: Access Control — Medium

**Task ID:** `ex_025`  
**Domain:** access_control  
**Difficulty:** medium  
**Initial rules:** 6  
**Updates:** 4

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **40.6%**

### What makes it hard

A priority swap between two broadly-matching rules flips the winner for a large slice of scenarios. The swap looks like a minor bookkeeping change but has global behavioral consequences.

**Dominant interaction pattern:** scope exposure

### Initial Policy Summary

**Definitions:** {"new_account_threshold": 14, "lockout_threshold": 3, "mfa_grace_period": 30}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`

```yaml
definitions:
  new_account_threshold: 14
  lockout_threshold: 3
  mfa_grace_period: 30
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: temporary_lock
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - failed_login_count < {lockout_threshold}
  - has_mfa == False
  decision: temporary_lock
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - user_role in ['editor', 'admin', 'superadmin']
  - account_age_days <= 93
  decision: temporary_lock
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - failed_login_count <= 10
  decision: require_approval
  priority: 4
  overrides:
  - rule_2
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - user_role == 'viewer'
  decision: temporary_lock
  priority: 5
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - user_role == 'editor'
  - account_age_days >= 287
  - resource_sensitivity == 'restricted'
  decision: temporary_lock
  priority: 6
```

### Update Stream (4 updates)

1. `[narrow_scope]` Narrow scope of 'rule_1': add condition 'user_role == 'editor''
2. `[narrow_scope]` Narrow scope of 'rule_4': add condition 'failed_login_count > {lockout_threshold}'
3. `[widen_scope]` Widen scope of 'rule_1': remove condition 'user_role == 'editor''
4. `[override_existing]` Add override rule 'update_4_override' that overrides 'rule_3'

### What Changed (Gold vs Initial)

- Rules **added**: `update_4_override`
- **40.6%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 387, stale_rule_retained: 19

### Counterexample (initial policy is wrong here)

```
Scenario:  {'failed_login_count': 21, 'has_mfa': False, 'user_role': 'superadmin', 'account_age_days': 28, 'resource_sensitivity': 'restricted'}
Expected:  grant_access (rule: update_4_override)
Got (initial): temporary_lock (rule: rule_2)
```

---

## Example 4: Escalation — Medium

**Task ID:** `ex_031`  
**Domain:** escalation  
**Difficulty:** medium  
**Initial rules:** 6  
**Updates:** 4

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **31.4%**

### What makes it hard

An exception is carved out of a rule that already overrides another. Agents must track both the override relationship and the new exception without conflating them.

**Dominant interaction pattern:** priority inversion, revoke-exposes-fallback

### Initial Policy Summary

**Definitions:** {"sla_low": 48, "sla_medium": 36, "sla_high": 4, "sla_critical": 2}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`

```yaml
definitions:
  sla_low: 48
  sla_medium: 36
  sla_high: 4
  sla_critical: 2
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: page_oncall
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - is_security_related == True
  decision: escalate_l2
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - previous_escalations > {sla_high}
  decision: no_action
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - customer_tier in ['enterprise', 'free']
  decision: page_oncall
  priority: 4
  overrides:
  - rule_2
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - customer_tier == 'pro'
  - is_security_related == True
  decision: escalate_l2
  priority: 5
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - previous_escalations > {sla_high}
  - is_security_related == False
  decision: escalate_l2
  priority: 6
  overrides:
  - rule_1
  - rule_4
```

### Update Stream (4 updates)

1. `[change_decision]` Change decision of 'rule_1' from escalate_l2 to no_action
2. `[change_priority]` Swap priorities: 'rule_3' (pri 4) <-> 'rule_1' (pri 2)
3. `[change_priority]` Swap priorities: 'rule_3' (pri 2) <-> 'rule_5' (pri 6)
4. `[revoke_rule]` Revoke rule: rule_4

### What Changed (Gold vs Initial)

- Rules **removed**: `rule_4`
- **31.4%** of scenarios now produce a different decision
- Failure breakdown: wrong_decision: 274, stale_rule_retained: 30, wrong_priority: 10

### Counterexample (initial policy is wrong here)

```
Scenario:  {'is_security_related': False, 'previous_escalations': 11, 'customer_tier': 'free'}
Expected:  page_oncall (rule: rule_3)
Got (initial): escalate_l2 (rule: rule_5)
```

---

## Example 5: Refund — Medium

**Task ID:** `ex_044`  
**Domain:** refund  
**Difficulty:** medium  
**Initial rules:** 6  
**Updates:** 5

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **31.0%**

### What makes it hard

Changing 'standard_window' from 30 to 45 silently expands the applicability of every rule that references it. Agents that edit rules one-by-one often miss that the definition already did the work — or double-apply it.

**Dominant interaction pattern:** priority inversion, override/exception chain, scope exposure

**Update interactions:**

- Update 4 (change_priority) → Update 5 (add_exception): priority reordering changes which rule the override/exception applies to

### Initial Policy Summary

**Definitions:** {"standard_window": 60, "extended_window": 120, "max_refund_amount": 100}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`

```yaml
definitions:
  standard_window: 60
  extended_window: 120
  max_refund_amount: 100
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: offer_store_credit
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - customer_tier == 'bronze'
  decision: deny_refund
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - is_final_sale == True
  decision: approve_refund
  priority: 3
  overrides:
  - rule_1
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - customer_tier == 'gold'
  - item_condition in ['unopened']
  - is_final_sale == True
  decision: escalate_to_manager
  priority: 4
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - purchase_channel in ['online', 'in_store']
  decision: offer_store_credit
  priority: 5
  overrides:
  - rule_1
  - rule_3
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - item_condition in ['unopened']
  decision: offer_store_credit
  priority: 6
```

### Update Stream (5 updates)

1. `[narrow_scope]` Narrow scope of 'rule_3': add condition 'customer_tier in ['bronze', 'platinum']'
2. `[add_exception]` Add exception to 'rule_2': when 'is_final_sale == True', decision becomes 'escalate_to_manager'
3. `[change_decision]` Change decision of 'rule_1' from deny_refund to approve_refund
4. `[change_priority]` Swap priorities: 'rule_1' (pri 2) <-> 'update_2_exception' (pri 7)
5. `[add_exception]` Add exception to 'rule_3': when 'customer_tier in ['gold']', decision becomes 'offer_store_credit'

### What Changed (Gold vs Initial)

- Rules **added**: `update_2_exception`, `update_5_exception`
- **31.0%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 310

### Counterexample (initial policy is wrong here)

```
Scenario:  {'customer_tier': 'bronze', 'is_final_sale': True, 'item_condition': 'unopened', 'purchase_channel': 'in_store'}
Expected:  approve_refund (rule: rule_1)
Got (initial): offer_store_credit (rule: rule_5)
```

---

## Example 6: Approval — Hard

**Task ID:** `ex_055`  
**Domain:** approval  
**Difficulty:** hard  
**Initial rules:** 8  
**Updates:** 5

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **75.1%**

### What makes it hard

Narrowing a rule's scope removes it from some scenarios, making a previously-shadowed lower-priority rule the winner there. An exception is then added to that exposed rule. Two-step interactions are easy to miss.

**Dominant interaction pattern:** scope exposure, revoke-exposes-fallback

**Update interactions:**

- Update 2 (revoke) → Update 3 (widen_scope): revoking exposes new winners that the later change then modifies

### Initial Policy Summary

**Definitions:** {"auto_approve_limit": 100, "manager_limit": 1000, "director_limit": 10000}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`, `rule_6`, `rule_7`

```yaml
definitions:
  auto_approve_limit: 100
  manager_limit: 1000
  director_limit: 10000
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: deny
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - requester_level == 'manager'
  - amount >= 43426
  - department in ['legal', 'ops', 'sales', 'marketing']
  decision: deny
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - amount < 33618
  - requester_level in ['intern', 'director']
  - is_recurring == True
  decision: auto_approve
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - expense_type in ['software', 'hardware', 'training', 'travel']
  - department == 'ops'
  - is_budgeted == False
  decision: director_approval
  priority: 4
  overrides:
  - rule_1
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - department == 'legal'
  - is_recurring == True
  decision: vp_approval
  priority: 5
  overrides:
  - rule_3
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - expense_type == 'travel'
  - is_recurring == False
  - amount <= {director_limit}
  decision: director_approval
  priority: 6
  overrides:
  - rule_1
- id: rule_6
  description: Auto-generated rule 6
  conditions:
  - expense_type == 'consulting'
  - is_recurring == False
  - is_budgeted == False
  decision: auto_approve
  priority: 7
  overrides:
  - rule_5
  - rule_4
- id: rule_7
  description: Auto-generated rule 7
  conditions:
  - is_budgeted == False
  - department == 'sales'
  decision: director_approval
  priority: 8
```

### Update Stream (5 updates)

1. `[override_existing]` Add override rule 'update_1_override' that overrides 'rule_1'
2. `[revoke_rule]` Revoke rule: rule_2
3. `[widen_scope]` Widen scope of 'rule_7': remove condition 'department == 'sales''
4. `[change_decision]` Change decision of 'rule_7' from director_approval to manager_approval
5. `[change_decision]` Change decision of 'rule_3' from director_approval to deny

### What Changed (Gold vs Initial)

- Rules **added**: `update_1_override`
- Rules **removed**: `rule_2`
- **75.1%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 708, wrong_decision: 43

### Counterexample (initial policy is wrong here)

```
Scenario:  {'requester_level': 'unknown_value', 'amount': 116859, 'department': 'ops', 'expense_type': 'consulting', 'is_budgeted': False, 'is_recurring': False}
Expected:  manager_approval (rule: rule_7)
Got (initial): auto_approve (rule: rule_6)
```

---

## Example 7: Access Control — Hard

**Task ID:** `ex_063`  
**Domain:** access_control  
**Difficulty:** hard  
**Initial rules:** 8  
**Updates:** 6

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **21.2%**

### What makes it hard

Three sequential override operations build a chain: A overrides B, then C overrides A, then B is revoked. Agents must reason about transitive precedence after each step, not just apply updates in isolation.

**Dominant interaction pattern:** definition propagation, priority inversion, scope exposure, revoke-exposes-fallback

**Update interactions:**

- Update 5 (change_definition) → Update 1 (narrow_scope): the definition change propagates into the scope/exception modification
- Update 3 (revoke) → Update 4 (override_existing): revoking exposes new winners that the later change then modifies
- Update 2 (change_priority) → Update 4 (override_existing): priority reordering changes which rule the override/exception applies to

### Initial Policy Summary

**Definitions:** {"new_account_threshold": 14, "lockout_threshold": 5, "mfa_grace_period": 60}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`, `rule_6`, `rule_7`

```yaml
definitions:
  new_account_threshold: 14
  lockout_threshold: 5
  mfa_grace_period: 60
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: temporary_lock
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - has_mfa == False
  - user_role in ['editor']
  decision: require_mfa
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - failed_login_count > {new_account_threshold}
  decision: deny_access
  priority: 3
  overrides:
  - rule_1
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - account_age_days >= 117
  decision: require_approval
  priority: 4
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - failed_login_count < {new_account_threshold}
  - resource_sensitivity in ['confidential', 'public', 'restricted']
  decision: temporary_lock
  priority: 5
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - account_age_days >= {lockout_threshold}
  decision: grant_access
  priority: 6
  overrides:
  - rule_1
  - rule_2
- id: rule_6
  description: Auto-generated rule 6
  conditions:
  - user_role in ['viewer', 'superadmin', 'admin']
  - is_during_business_hours == False
  decision: require_approval
  priority: 7
  overrides:
  - rule_3
- id: rule_7
  description: Auto-generated rule 7
  conditions:
  - has_mfa == False
  decision: temporary_lock
  priority: 8
  overrides:
  - rule_1
  - rule_4
```

### Update Stream (6 updates)

1. `[narrow_scope]` Narrow scope of 'rule_2': add condition 'failed_login_count > 7'
2. `[change_priority]` Swap priorities: 'rule_4' (pri 5) <-> 'rule_3' (pri 4)
3. `[revoke_rule]` Revoke rule: rule_3
4. `[override_existing]` Add override rule 'update_4_override' that overrides 'rule_6'
5. `[change_definition]` Change definition 'lockout_threshold' from 5 to 5
6. `[change_priority]` Swap priorities: 'rule_6' (pri 7) <-> 'rule_5' (pri 6)

### What Changed (Gold vs Initial)

- Rules **added**: `update_4_override`
- Rules **removed**: `rule_3`
- **21.2%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 116, wrong_decision: 96

### Counterexample (initial policy is wrong here)

```
Scenario:  {'has_mfa': False, 'user_role': 'viewer', 'failed_login_count': 0, 'resource_sensitivity': 'public', 'account_age_days': 0, 'is_during_business_hours': True}
Expected:  deny_access (rule: update_4_override)
Got (initial): temporary_lock (rule: rule_7)
```

---

## Example 8: Escalation — Hard

**Task ID:** `ex_071`  
**Domain:** escalation  
**Difficulty:** hard  
**Initial rules:** 8  
**Updates:** 6

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **49.5%**

### What makes it hard

A rule is revoked, then a surviving sibling rule is widened to cover more cases. The widening interacts with the now-absent rule: scenarios that used to hit the revoked rule now fall through to the widened sibling with a different decision.

**Dominant interaction pattern:** sequential local edits

### Initial Policy Summary

**Definitions:** {"sla_low": 72, "sla_medium": 48, "sla_high": 12, "sla_critical": 1}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`, `rule_6`, `rule_7`

```yaml
definitions:
  sla_low: 72
  sla_medium: 48
  sla_high: 12
  sla_critical: 1
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: page_oncall
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - customer_tier == 'starter'
  - is_security_related == True
  decision: page_oncall
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - previous_escalations >= {sla_critical}
  decision: escalate_l2
  priority: 3
  overrides:
  - rule_1
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - previous_escalations > {sla_critical}
  - ticket_age_hours >= {sla_critical}
  decision: no_action
  priority: 4
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - ticket_age_hours <= {sla_high}
  - customer_tier in ['pro', 'free']
  - previous_escalations < {sla_critical}
  decision: escalate_l2
  priority: 5
  overrides:
  - rule_2
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - is_revenue_impacting == False
  - previous_escalations > {sla_critical}
  decision: escalate_l3
  priority: 6
- id: rule_6
  description: Auto-generated rule 6
  conditions:
  - previous_escalations <= {sla_critical}
  decision: no_action
  priority: 7
- id: rule_7
  description: Auto-generated rule 7
  conditions:
  - previous_escalations < 1
  - is_security_related == True
  - severity == 'high'
  decision: page_oncall
  priority: 8
```

### Update Stream (6 updates)

1. `[override_existing]` Add override rule 'update_1_override' that overrides 'rule_4'
2. `[add_rule]` Add new rule: update_2_new_rule
3. `[add_rule]` Add new rule: update_3_new_rule
4. `[add_rule]` Add new rule: update_4_new_rule
5. `[change_decision]` Change decision of 'update_3_new_rule' from escalate_l2 to no_action
6. `[change_decision]` Change decision of 'update_2_new_rule' from no_action to escalate_manager

### What Changed (Gold vs Initial)

- Rules **added**: `update_1_override`, `update_2_new_rule`, `update_3_new_rule`, `update_4_new_rule`
- **49.5%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 495

### Counterexample (initial policy is wrong here)

```
Scenario:  {'customer_tier': 'starter', 'is_security_related': False, 'previous_escalations': 1, 'ticket_age_hours': 18, 'is_revenue_impacting': True, 'severity': 'high'}
Expected:  page_oncall (rule: update_1_override)
Got (initial): no_action (rule: rule_6)
```

---

## Example 9: Refund — Very Hard

**Task ID:** `ex_088`  
**Domain:** refund  
**Difficulty:** very_hard  
**Initial rules:** 10  
**Updates:** 7

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **59.7%**

### What makes it hard

Four add_exception operations each inherit their parent rule's conditions plus one extra. Priority inversions then reorder these stacked exceptions. Maintaining correct layering under both changes requires tracking 10+ rule interactions simultaneously.

**Dominant interaction pattern:** definition propagation, priority inversion

**Update interactions:**

- Update 2 (change_priority) → Update 5 (override_existing): priority reordering changes which rule the override/exception applies to
- Update 3 (change_priority) → Update 5 (override_existing): priority reordering changes which rule the override/exception applies to
- Update 4 (change_priority) → Update 5 (override_existing): priority reordering changes which rule the override/exception applies to

### Initial Policy Summary

**Definitions:** {"standard_window": 60, "extended_window": 60, "max_refund_amount": 500}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`, `rule_6`, `rule_7`, `rule_8`, `rule_9`

```yaml
definitions:
  standard_window: 60
  extended_window: 60
  max_refund_amount: 500
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: offer_store_credit
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - purchase_channel == 'phone'
  decision: approve_refund
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - purchase_channel == 'online'
  - customer_tier in ['silver', 'platinum', 'gold']
  decision: escalate_to_manager
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - item_condition == 'damaged'
  decision: escalate_to_manager
  priority: 4
  overrides:
  - rule_2
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - item_price > {standard_window}
  decision: offer_store_credit
  priority: 5
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - customer_tier in ['platinum', 'silver', 'bronze']
  decision: offer_store_credit
  priority: 6
  overrides:
  - rule_2
- id: rule_6
  description: Auto-generated rule 6
  conditions:
  - customer_tier in ['bronze', 'platinum', 'gold']
  decision: approve_refund
  priority: 7
  overrides:
  - rule_2
  - rule_4
- id: rule_7
  description: Auto-generated rule 7
  conditions:
  - is_final_sale == False
  - purchase_age_days <= 147
  decision: offer_store_credit
  priority: 8
  overrides:
  - rule_6
  - rule_4
- id: rule_8
  description: Auto-generated rule 8
  conditions:
  - is_final_sale == False
  - item_condition == 'defective'
  - customer_tier in ['platinum']
  decision: escalate_to_manager
  priority: 9
  overrides:
  - rule_2
  - rule_5
- id: rule_9
  description: Auto-generated rule 9
  conditions:
  - purchase_channel == 'online'
  - item_condition in ['unopened']
  decision: escalate_to_manager
  priority: 10
```

### Update Stream (7 updates)

1. `[change_decision]` Change decision of 'rule_9' from escalate_to_manager to deny_refund
2. `[change_priority]` Swap priorities: 'rule_7' (pri 8) <-> 'rule_3' (pri 4)
3. `[change_priority]` Swap priorities: 'rule_5' (pri 6) <-> 'rule_7' (pri 4)
4. `[change_priority]` Swap priorities: 'rule_9' (pri 10) <-> 'rule_5' (pri 4)
5. `[override_existing]` Add override rule 'update_5_override' that overrides 'rule_6'
6. `[change_definition]` Change definition 'standard_window' from 60 to 45

### What Changed (Gold vs Initial)

- Rules **added**: `update_5_override`
- **59.7%** of scenarios now produce a different decision
- Failure breakdown: wrong_priority: 483, wrong_decision: 70, stale_rule_retained: 44

### Counterexample (initial policy is wrong here)

```
Scenario:  {'purchase_channel': 'online', 'customer_tier': 'platinum', 'item_condition': 'unopened', 'item_price': 1342, 'is_final_sale': True, 'purchase_age_days': 187}
Expected:  offer_store_credit (rule: rule_5)
Got (initial): escalate_to_manager (rule: rule_9)
```

---

## Example 10: Approval — Very Hard

**Task ID:** `ex_099`  
**Domain:** approval  
**Difficulty:** very_hard  
**Initial rules:** 10  
**Updates:** 8

**Behavioral gap** (fraction of scenarios where initial ≠ gold): **41.6%**

### What makes it hard

All nine update types appear across 8 sequential changes. A definition change in step 2 affects conditions that are narrowed in step 5. A rule revoked in step 3 was an override target for a rule added in step 6. The update stream is deliberately non-local: almost every step touches something a prior step already changed.

**Dominant interaction pattern:** priority inversion, scope exposure, revoke-exposes-fallback

**Update interactions:**

- Update 1 (revoke) → Update 6 (widen_scope): revoking exposes new winners that the later change then modifies
- Update 1 (revoke) → Update 8 (widen_scope): revoking exposes new winners that the later change then modifies
- Update 5 (revoke) → Update 6 (widen_scope): revoking exposes new winners that the later change then modifies
- Update 5 (revoke) → Update 8 (widen_scope): revoking exposes new winners that the later change then modifies

### Initial Policy Summary

**Definitions:** {"auto_approve_limit": 250, "manager_limit": 2500, "director_limit": 10000}

**Rules:** `default_action`, `rule_1`, `rule_2`, `rule_3`, `rule_4`, `rule_5`, `rule_6`, `rule_7`, `rule_8`, `rule_9`

```yaml
definitions:
  auto_approve_limit: 250
  manager_limit: 2500
  director_limit: 10000
rules:
- id: default_action
  description: Default fallback when no other rule matches
  conditions: []
  decision: deny
  priority: 1
- id: rule_1
  description: Auto-generated rule 1
  conditions:
  - department == 'engineering'
  - is_recurring == False
  - is_budgeted == False
  decision: deny
  priority: 2
- id: rule_2
  description: Auto-generated rule 2
  conditions:
  - is_recurring == False
  - is_budgeted == True
  - amount > {director_limit}
  decision: director_approval
  priority: 3
- id: rule_3
  description: Auto-generated rule 3
  conditions:
  - department in ['engineering', 'legal', 'sales']
  - is_recurring == False
  - expense_type == 'hardware'
  decision: deny
  priority: 4
  overrides:
  - rule_2
- id: rule_4
  description: Auto-generated rule 4
  conditions:
  - amount <= 3364
  - expense_type == 'software'
  - department in ['legal', 'sales', 'marketing', 'engineering']
  decision: auto_approve
  priority: 5
  overrides:
  - rule_2
- id: rule_5
  description: Auto-generated rule 5
  conditions:
  - expense_type in ['hardware', 'travel']
  - amount >= {auto_approve_limit}
  - is_recurring == True
  decision: auto_approve
  priority: 6
- id: rule_6
  description: Auto-generated rule 6
  conditions:
  - requester_level == 'ic'
  - is_budgeted == False
  decision: vp_approval
  priority: 7
- id: rule_7
  description: Auto-generated rule 7
  conditions:
  - is_recurring == True
  decision: deny
  priority: 8
- id: rule_8
  description: Auto-generated rule 8
  conditions:
  - amount > {manager_limit}
  decision: manager_approval
  priority: 9
- id: rule_9
  description: Auto-generated rule 9
  conditions:
  - is_budgeted == False
  decision: vp_approval
  priority: 10
```

### Update Stream (8 updates)

1. `[revoke_rule]` Revoke rule: rule_4
2. `[narrow_scope]` Narrow scope of 'rule_3': add condition 'expense_type == 'travel''
3. `[change_decision]` Change decision of 'rule_2' from director_approval to vp_approval
4. `[change_priority]` Swap priorities: 'rule_8' (pri 9) <-> 'rule_9' (pri 10)
5. `[revoke_rule]` Revoke rule: rule_5
6. `[widen_scope]` Widen scope of 'rule_6': remove condition 'requester_level == 'ic''
7. `[change_decision]` Change decision of 'rule_3' from deny to manager_approval
8. `[widen_scope]` Widen scope of 'rule_2': remove condition 'is_budgeted == True'

### What Changed (Gold vs Initial)

- Rules **removed**: `rule_4`, `rule_5`
- **41.6%** of scenarios now produce a different decision
- Failure breakdown: wrong_decision: 416

### Counterexample (initial policy is wrong here)

```
Scenario:  {'department': 'unknown_value', 'is_recurring': False, 'is_budgeted': False, 'amount': 25357, 'expense_type': 'hardware'}
Expected:  manager_approval (rule: rule_8)
Got (initial): vp_approval (rule: rule_9)
```
