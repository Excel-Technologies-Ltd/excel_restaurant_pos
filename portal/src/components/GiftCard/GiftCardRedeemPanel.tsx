import { useFrappePostCall } from "frappe-react-sdk";
import { useState } from "react";

type AppliedGiftCard = {
  gift_card_code: string;
  redeemed_amount: number;
};

type Props = {
  /** Draft Sales Invoice name — required for gift card APIs */
  salesInvoice: string | null | undefined;
  /** Disable when promo coupon is already applied */
  promoCouponActive?: boolean;
  onAppliedChange?: (rows: AppliedGiftCard[], discountTotal: number) => void;
};

/**
 * Multi gift-card redeem panel for checkout.
 * Uses api.gift_cards.verify / apply / discard against a draft Sales Invoice.
 */
const GiftCardRedeemPanel = ({
  salesInvoice,
  promoCouponActive,
  onAppliedChange,
}: Props) => {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string>("");
  const [applied, setApplied] = useState<AppliedGiftCard[]>([]);

  const { call: verifyGift } = useFrappePostCall("api.gift_cards.verify");
  const { call: applyGift } = useFrappePostCall("api.gift_cards.apply");
  const { call: discardGift } = useFrappePostCall("api.gift_cards.discard");

  if (!salesInvoice) {
    return (
      <div className="text-xs text-gray-500 mt-2">
        Save a draft Sales Invoice before redeeming gift cards.
      </div>
    );
  }

  if (promoCouponActive) {
    return (
      <div className="text-xs text-amber-700 mt-2">
        Remove the promotional coupon to redeem gift cards.
      </div>
    );
  }

  const syncApplied = (rows: AppliedGiftCard[], discount: number) => {
    setApplied(rows);
    onAppliedChange?.(rows, discount);
  };

  const handleVerify = async () => {
    setError("");
    setPreview("");
    if (!code.trim()) return;
    try {
      const res = await verifyGift({
        sales_invoice: salesInvoice,
        gift_card_code: code.trim(),
      });
      const m = res?.message;
      if (m?.valid) {
        setPreview(
          `Balance ${m.available_balance} → redeem ${m.redeemed_amount}`
        );
      } else {
        setError(m?.message || "Invalid gift card");
      }
    } catch (e: any) {
      setError(e?.message || "Verify failed");
    }
  };

  const handleApply = async () => {
    setError("");
    if (!code.trim()) return;
    try {
      const res = await applyGift({
        sales_invoice: salesInvoice,
        gift_card_code: code.trim(),
      });
      const m = res?.message;
      if (m?.applied) {
        syncApplied(m.applied_gift_cards || [], Number(m.invoice_discount_amount || 0));
        setCode("");
        setPreview("");
      } else {
        setError(m?.message || "Apply failed");
      }
    } catch (e: any) {
      setError(e?.message || "Apply failed");
    }
  };

  const handleDiscard = async (giftCode?: string) => {
    setError("");
    try {
      const args: Record<string, string> = { sales_invoice: salesInvoice };
      if (giftCode) args.gift_card_code = giftCode;
      const res = await discardGift(args);
      const m = res?.message;
      syncApplied(m?.applied_gift_cards || [], Number(m?.invoice_discount_amount || 0));
    } catch (e: any) {
      setError(e?.message || "Remove failed");
    }
  };

  return (
    <div className="mt-3 border rounded-md p-3 space-y-2">
      <h3 className="text-xs font-semibold">Gift Cards</h3>
      <div className="flex gap-2">
        <input
          className="flex-1 border rounded px-2 py-1.5 text-sm"
          placeholder="Enter or scan gift card code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleApply();
            }
          }}
        />
        <button
          type="button"
          className="text-xs border px-2 rounded"
          onClick={handleVerify}
        >
          Verify
        </button>
        <button
          type="button"
          className="text-xs bg-primaryColor text-white px-2 rounded"
          onClick={handleApply}
        >
          Apply
        </button>
      </div>
      {preview && <p className="text-xs text-green-700">{preview}</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
      {applied.length > 0 && (
        <ul className="text-xs space-y-1">
          {applied.map((row) => (
            <li
              key={row.gift_card_code}
              className="flex justify-between items-center bg-gray-50 px-2 py-1 rounded"
            >
              <span>
                {row.gift_card_code}: {row.redeemed_amount}
              </span>
              <button
                type="button"
                className="text-red-600 underline"
                onClick={() => handleDiscard(row.gift_card_code)}
              >
                Remove
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="text-red-600 underline"
              onClick={() => handleDiscard()}
            >
              Clear all gift cards
            </button>
          </li>
        </ul>
      )}
    </div>
  );
};

export default GiftCardRedeemPanel;
