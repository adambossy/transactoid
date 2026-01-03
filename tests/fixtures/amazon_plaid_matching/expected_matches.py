"""Expected matches between Amazon orders and Plaid transactions.

This mapping represents the ground truth for matching tests, validated
against real transaction data.
"""

# Maps Amazon order_id -> Plaid plaid_transaction_id
# All 25 orders have exactly one matching Plaid transaction
EXPECTED_MATCHES: dict[str, int] = {
    # Order 1: $150.25, ordered 12/29, posted 12/30
    "113-5524816-2451403": 839,
    # Order 2: $39.27, ordered 12/28, posted 12/29
    "112-5793878-2607402": 830,
    # Order 3: $49.77, ordered 12/27, posted 12/30
    "113-2183381-7505026": 841,
    # Order 4: $28.30, ordered 12/27, posted 12/28
    "113-5891569-5979439": 825,
    # Order 5: $87.09, ordered 12/27, posted 12/28
    "113-0845620-0483424": 826,
    # Order 6: $7.61, ordered 12/26, posted 12/29
    "112-7570534-9890666": 831,
    # Order 7: $10.88, ordered 12/22, posted 12/23
    "113-5622584-5484267": 797,
    # Order 8: $40.47, ordered 12/20, posted 12/20
    "112-4502156-7842663": 771,
    # Order 9: $38.21, ordered 12/20, posted 12/21
    "113-5851169-0722617": 779,
    # Order 10: $8.28, ordered 12/20, posted 12/21
    "113-6936344-4293026": 778,
    # Order 11: $45.30, ordered 12/18, posted 12/22
    "113-8425491-4935405": 791,
    # Order 12: $28.27, ordered 12/16, posted 12/17
    "113-3375353-9086669": 742,
    # Order 13: $29.97, ordered 12/16, posted 12/17
    "113-4246085-4890616": 743,
    # Order 14: $9.19, ordered 12/14, posted 12/16
    "112-3110699-5201836": 727,
    # Order 15: $14.34, ordered 12/05, posted 12/06
    "112-8580438-6561817": 643,
    # Order 16: $6.52, ordered 12/01, posted 12/02
    "112-6047621-2461033": 606,
    # Order 17: $49.98, ordered 11/22, posted 11/23
    "112-9348880-7178650": 27,
    # Order 18: $18.94, ordered 11/12, posted 11/12
    "112-2711996-7841038": 89,
    # Order 19: $75.90, ordered 11/11, posted 11/12
    "113-1180294-0059432": 98,
    # Order 20: $48.93, ordered 11/02, posted 11/02
    "112-8565765-9771446": 148,
    # Order 21: $10.98, ordered 10/26, posted 10/27
    "112-9508317-5020242": 189,
    # Order 22: $59.24, ordered 10/24, posted 10/25
    "112-9053665-8377064": 198,
    # Order 23: $46.51, ordered 10/24, posted 10/24
    "112-5097650-2529056": 204,
    # Order 24: $8.69, ordered 10/24, posted 10/24
    "113-1031800-1734626": 203,
    # Order 25: $207.92, ordered 10/23, posted 10/24
    "113-3910520-0532212": 202,
}
