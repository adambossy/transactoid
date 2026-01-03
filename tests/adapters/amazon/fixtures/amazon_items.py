"""Amazon item fixtures for matching tests.

These are real items from Amazon CSV exports corresponding to the
orders in amazon_orders.py.
"""

from transactoid.adapters.amazon.csv_loader import AmazonItem


def create_amazon_items() -> list[AmazonItem]:
    """Create fixture list of 39 Amazon items for matching tests.

    Returns:
        List of AmazonItem instances grouped by order_id.
    """
    return [
        # Order 1: 113-5524816-2451403 (1 item)
        AmazonItem(
            order_id="113-5524816-2451403",
            asin="B0D47SC68P",
            description="Aesop Reverence Aromatique Hand Wash",
            price_cents=13800,
            quantity=1,
        ),
        # Order 2: 112-5793878-2607402 (1 item)
        AmazonItem(
            order_id="112-5793878-2607402",
            asin="B0725BK81G",
            description="Gillette Mach3 Razor Blades, 15 Count",
            price_cents=3797,
            quantity=1,
        ),
        # Order 3: 113-2183381-7505026 (2 items)
        AmazonItem(
            order_id="113-2183381-7505026",
            asin="B077D3JKVR",
            description="Pampers Aqua Pure Baby Wipes, 336 Count",
            price_cents=1819,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-2183381-7505026",
            asin="B082QBSJ6L",
            description="Pampers Pure Protection Diapers, Size 1",
            price_cents=2997,
            quantity=1,
        ),
        # Order 4: 113-5891569-5979439 (1 item)
        AmazonItem(
            order_id="113-5891569-5979439",
            asin="B0CJ55HG7H",
            description="Dreo Scale-Inhibitor Cartridge 3-Pack",
            price_cents=2599,
            quantity=1,
        ),
        # Order 5: 113-0845620-0483424 (1 item)
        AmazonItem(
            order_id="113-0845620-0483424",
            asin="B0CB4D5R9Z",
            description="Dreo 6L Humidifiers for Bedroom",
            price_cents=7998,
            quantity=1,
        ),
        # Order 6: 112-7570534-9890666 (1 item)
        AmazonItem(
            order_id="112-7570534-9890666",
            asin="B0FR4QJSRX",
            description="IOUALEY 35mm Quick Release Plate",
            price_cents=699,
            quantity=1,
        ),
        # Order 7: 113-5622584-5484267 (1 item)
        AmazonItem(
            order_id="113-5622584-5484267",
            asin="B09FYWQ44L",
            description="Hot Glue Gun Kit with 30 Glue Sticks",
            price_cents=999,
            quantity=1,
        ),
        # Order 8: 112-4502156-7842663 (2 items)
        AmazonItem(
            order_id="112-4502156-7842663",
            asin="B07MHJFRBJ",
            description="Bounty Quick Size Paper Towels, 8 Rolls",
            price_cents=2442,
            quantity=1,
        ),
        AmazonItem(
            order_id="112-4502156-7842663",
            asin="B08MVF9YW1",
            description="Mederma Cold Sore Discreet Patch",
            price_cents=1398,
            quantity=1,
        ),
        # Order 9: 113-5851169-0722617 (2 items)
        AmazonItem(
            order_id="113-5851169-0722617",
            asin="B0DKG43DDC",
            description="La Petite Creme French Baby Lotion",
            price_cents=2299,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-5851169-0722617",
            asin="B08MVF9YW1",
            description="Mederma Cold Sore Discreet Patch",
            price_cents=1398,
            quantity=1,
        ),
        # Order 10: 113-6936344-4293026 (1 item)
        AmazonItem(
            order_id="113-6936344-4293026",
            asin="B002QYW8LW",
            description="Baby Banana Toddler Toothbrush",
            price_cents=761,
            quantity=1,
        ),
        # Order 11: 113-8425491-4935405 (3 items)
        AmazonItem(
            order_id="113-8425491-4935405",
            asin="B07L9176CV",
            description="KIDSUN Infant Baby Girls Mary Jane Shoes",
            price_cents=1399,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-8425491-4935405",
            asin="B0DHVK72C4",
            description="ANYANIME 6 Pairs Toddler Ruffle Socks",
            price_cents=1499,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-8425491-4935405",
            asin="B0B4WGYGZ1",
            description="Sugarmelon Velvet Bow Headbands",
            price_cents=1499,
            quantity=1,
        ),
        # Order 12: 113-3375353-9086669 (1 item)
        AmazonItem(
            order_id="113-3375353-9086669",
            asin="B0FH5LGLB2",
            description="Living Well Remineralizing Tooth Powder",
            price_cents=2597,
            quantity=1,
        ),
        # Order 13: 113-4246085-4890616 (1 item)
        AmazonItem(
            order_id="113-4246085-4890616",
            asin="B082QBSJ6L",
            description="Pampers Pure Protection Diapers, Size 1",
            price_cents=2997,
            quantity=1,
        ),
        # Order 14: 112-3110699-5201836 (1 item)
        AmazonItem(
            order_id="112-3110699-5201836",
            asin="B00RSB6I1E",
            description="Scotch Heavy Duty Packaging Tape",
            price_cents=844,
            quantity=1,
        ),
        # Order 15: 112-8580438-6561817 (1 item)
        AmazonItem(
            order_id="112-8580438-6561817",
            asin="B0BVY2XKJX",
            description="OxiClean Max Force Stain Remover Spray",
            price_cents=1317,
            quantity=1,
        ),
        # Order 16: 112-6047621-2461033 (1 item)
        AmazonItem(
            order_id="112-6047621-2461033",
            asin="B08CKG9SBC",
            description="SmoTecQ Microfiber Lens Cleaning Cloths",
            price_cents=599,
            quantity=1,
        ),
        # Order 17: 112-9348880-7178650 (1 item)
        AmazonItem(
            order_id="112-9348880-7178650",
            asin="B00OPBIP02",
            description="BioGaia Baby Probiotic Drops + Vitamin D",
            price_cents=4998,
            quantity=1,
        ),
        # Order 18: 112-2711996-7841038 (1 item)
        AmazonItem(
            order_id="112-2711996-7841038",
            asin="B0F77H8HWB",
            description="ZIWI Peak Wet Cat Food, Grain Free",
            price_cents=1739,
            quantity=1,
        ),
        # Order 19: 113-1180294-0059432 (2 items)
        AmazonItem(
            order_id="113-1180294-0059432",
            asin="B00NAG7AF4",
            description="BioGaia Protectis Baby Probiotic Drops",
            price_cents=2697,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-1180294-0059432",
            asin="B0DT7M6JND",
            description="Tiki Cat Liquid Meal Replacer, 6 oz",
            price_cents=4494,
            quantity=1,
        ),
        # Order 20: 112-8565765-9771446 (1 item)
        AmazonItem(
            order_id="112-8565765-9771446",
            asin="B0DT7M6JND",
            description="Tiki Cat Liquid Meal Replacer, 6 oz",
            price_cents=4494,
            quantity=1,
        ),
        # Order 21: 112-9508317-5020242 (2 items - same product)
        AmazonItem(
            order_id="112-9508317-5020242",
            asin="B0014D3MGG",
            description="TUMS Extra Strength Antacid, 96 count",
            price_cents=549,
            quantity=2,
        ),
        AmazonItem(
            order_id="112-9508317-5020242",
            asin="B0014D3MGG",
            description="TUMS Extra Strength Antacid, 96 count",
            price_cents=549,
            quantity=2,
        ),
        # Order 22: 112-9053665-8377064 (4 items - duplicates from combined accounts)
        AmazonItem(
            order_id="112-9053665-8377064",
            asin="B08F7H8SBP",
            description="simplehuman Code M Trash Bags, 100 Count",
            price_cents=2999,
            quantity=1,
        ),
        AmazonItem(
            order_id="112-9053665-8377064",
            asin="B07MHJFRBJ",
            description="Bounty Quick Size Paper Towels, 8 Rolls",
            price_cents=2442,
            quantity=1,
        ),
        AmazonItem(
            order_id="112-9053665-8377064",
            asin="B08F7H8SBP",
            description="simplehuman Code M Trash Bags, 100 Count",
            price_cents=2999,
            quantity=1,
        ),
        AmazonItem(
            order_id="112-9053665-8377064",
            asin="B07MHJFRBJ",
            description="Bounty Quick Size Paper Towels, 8 Rolls",
            price_cents=2442,
            quantity=1,
        ),
        # Order 23: 112-5097650-2529056 (2 items - same product)
        AmazonItem(
            order_id="112-5097650-2529056",
            asin="B0DT7M6JND",
            description="Tiki Cat Liquid Meal Replacer, 6 oz",
            price_cents=4272,
            quantity=1,
        ),
        AmazonItem(
            order_id="112-5097650-2529056",
            asin="B0DT7M6JND",
            description="Tiki Cat Liquid Meal Replacer, 6 oz",
            price_cents=4272,
            quantity=1,
        ),
        # Order 24: 113-1031800-1734626 (2 items - same product)
        AmazonItem(
            order_id="113-1031800-1734626",
            asin="B07NLW25L9",
            description="Dr. Brown's Anti-Colic Baby Bottle",
            price_cents=799,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-1031800-1734626",
            asin="B07NLW25L9",
            description="Dr. Brown's Anti-Colic Baby Bottle",
            price_cents=799,
            quantity=1,
        ),
        # Order 25: 113-3910520-0532212 (3 items)
        AmazonItem(
            order_id="113-3910520-0532212",
            asin="B0CSK5RNQZ",
            description="Winner 100% Cotton Dry Wipes",
            price_cents=2299,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-3910520-0532212",
            asin="B0DHZPRTXP",
            description="Ljusmicker AirPods 4 Case Cover",
            price_cents=799,
            quantity=1,
        ),
        AmazonItem(
            order_id="113-3910520-0532212",
            asin="B0DGJ7HYG1",
            description="Apple AirPods 4 with Noise Cancellation",
            price_cents=15999,
            quantity=1,
        ),
    ]
