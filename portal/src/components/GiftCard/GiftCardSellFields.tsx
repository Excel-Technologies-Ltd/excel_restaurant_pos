import { useFrappePostCall } from "frappe-react-sdk";
import { useEffect, useState } from "react";

export type GiftCardType = "New" | "Existing";

export type GiftCardSellState = {
  custom_is_gift_card_item: number;
  custom_gift_card_type: GiftCardType;
  custom_gift_card_code?: string;
  custom_gift_amount?: number;
};

type Props = {
  isGiftCardItem: boolean;
  giftCardValue?: number;
  value: GiftCardSellState;
  onChange: (next: GiftCardSellState) => void;
};

type InactiveGiftCard = {
  name: string;
  coupon_code?: string;
  custom_discount_amount?: number;
};

/**
 * Sell-side controls when the selected Item is a gift card SKU.
 * New → face value from Item; Existing → pick Inactive code (search or scan).
 */
const GiftCardSellFields = ({
  isGiftCardItem,
  giftCardValue = 0,
  value,
  onChange,
}: Props) => {
  const [search, setScanOrSearch] = useState("");
  const [results, setResults] = useState<InactiveGiftCard[]>([]);
  const { call: listInactive } = useFrappePostCall("api.gift_cards.list_inactive");

  useEffect(() => {
    if (!isGiftCardItem) return;
    if (value.custom_gift_card_type === "New") {
      onChange({
        ...value,
        custom_is_gift_card_item: 1,
        custom_gift_card_type: "New",
        custom_gift_card_code: undefined,
        custom_gift_amount: giftCardValue || value.custom_gift_amount || 0,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGiftCardItem, giftCardValue, value.custom_gift_card_type]);

  if (!isGiftCardItem) return null;

  const selectExisting = (row: InactiveGiftCard) => {
    onChange({
      custom_is_gift_card_item: 1,
      custom_gift_card_type: "Existing",
      custom_gift_card_code: row.name,
      custom_gift_amount: Number(row.custom_discount_amount || 0),
    });
    setScanOrSearch(row.coupon_code || row.name);
    setResults([]);
  };

  const runSearch = async (term: string, autoSelectExact = false) => {
    setScanOrSearch(term);
    if (!term.trim()) {
      setResults([]);
      return;
    }
    try {
      const res = await listInactive({ search: term.trim(), limit: 20 });
      const rows: InactiveGiftCard[] = res?.message?.data || [];
      setResults(rows);
      if (autoSelectExact && rows.length === 1) {
        selectExisting(rows[0]);
      }
    } catch {
      setResults([]);
    }
  };

  return (
    <div className="mt-3 border rounded-md p-3 bg-gray-50 space-y-2">
      <p className="text-xs font-semibold text-gray-700">Gift Card</p>
      <div className="flex gap-2 text-sm">
        {(["New", "Existing"] as GiftCardType[]).map((t) => (
          <button
            key={t}
            type="button"
            className={`px-3 py-1 rounded border ${
              value.custom_gift_card_type === t
                ? "bg-primaryColor text-white border-primaryColor"
                : "bg-white"
            }`}
            onClick={() =>
              onChange({
                custom_is_gift_card_item: 1,
                custom_gift_card_type: t,
                custom_gift_card_code: t === "New" ? undefined : value.custom_gift_card_code,
                custom_gift_amount:
                  t === "New" ? giftCardValue : value.custom_gift_amount,
              })
            }
          >
            {t}
          </button>
        ))}
      </div>

      {value.custom_gift_card_type === "New" ? (
        <p className="text-sm text-gray-600">
          Face value: <b>{giftCardValue || value.custom_gift_amount || 0}</b>
        </p>
      ) : (
        <div className="relative">
          <label className="text-xs text-gray-500">
            Search or scan Inactive gift card
          </label>
          <input
            className="w-full border rounded px-2 py-1.5 text-sm mt-1"
            value={search}
            placeholder="Type code or scan QR/barcode"
            onChange={(e) => runSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (results[0]) {
                  selectExisting(results[0]);
                } else {
                  runSearch(search, true);
                }
              }
            }}
          />
          {results.length > 0 && (
            <ul className="absolute z-10 w-full bg-white border rounded mt-1 max-h-40 overflow-auto text-sm shadow">
              {results.map((row) => (
                <li key={row.name}>
                  <button
                    type="button"
                    className="w-full text-left px-2 py-1.5 hover:bg-gray-100"
                    onClick={() => selectExisting(row)}
                  >
                    {row.coupon_code || row.name} — {row.custom_discount_amount}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {value.custom_gift_card_code && (
            <p className="text-xs text-green-700 mt-1">
              Selected: {value.custom_gift_card_code} ({value.custom_gift_amount})
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default GiftCardSellFields;
