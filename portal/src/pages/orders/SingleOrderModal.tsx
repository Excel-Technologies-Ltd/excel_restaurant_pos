import {
  useFrappeAuth,
  useFrappeGetCall,
  useFrappeGetDoc,
  useFrappeGetDocList,
  useFrappePostCall,
  useFrappeUpdateDoc,
} from "frappe-react-sdk";
import React, { useEffect, useState } from "react";
import { FiPlus } from "react-icons/fi";

import toast from "react-hot-toast";
import { AiTwotoneDelete } from "react-icons/ai";
import { CgSpinner } from "react-icons/cg";
import { LuMinus } from "react-icons/lu";
import { RxCross2 } from "react-icons/rx";
import { useLoading } from "../../context/loadingContext";
import GiftCardRedeemPanel from "../../components/GiftCard/GiftCardRedeemPanel";
interface OrderItem {
  name?: string;
  qty?: number;
  rate?: number;
  is_parcel?: boolean;
  item?: string;
  item_name?: string;
}

interface PaymentMethod {
  id: string;
  method: string;
  amount: string;
  reference?: string;
}

const SingleOrderModal = ({
  orderId,
  closeModal,
  mutate,
  handleSalesInvoicePrint,
}: {
  orderId: string;
  closeModal: () => void;
  mutate: () => void;
  handleSalesInvoicePrint: (salesInvoice: string) => void;
}) => {
  const [discountLimit, setDiscountLimit] = useState<number>(0);
  const [orderItems, setOrderItems] = useState<OrderItem[]>([]);
  const [discountType, setDiscountType] = useState("percentage");

  const [coupon, setCoupon] = useState("");
  const [discountError, setDiscountError] = useState("");
  const [discount, setDiscount] = useState<string>("");
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const { startLoading, stopLoading } = useLoading();
  const { data: order } = useFrappeGetDoc("Table Order", orderId);
  console.log({ order, paymentMethods });
  // 10% tax rate
  //   api calling
  const { updateDoc, loading: isLoading } = useFrappeUpdateDoc();
  const { currentUser } = useFrappeAuth();
  const { data: mode_of_payment } = useFrappeGetDocList("Mode of Payment", {
    fields: ["name"],
  });
  const mode_of_payment_list = mode_of_payment?.map((item: any) => item?.name);
  console.log({ mode_of_payment_list });
  const { data: roles } = useFrappeGetCall(
    `excel_restaurant_pos.api.item.get_roles?user=${currentUser}`
  );
  const userRoles = roles?.message?.map((role: any) => role?.Role);

  const { data: settings } = useFrappeGetDoc(
    "Restaurant Settings",
    "Restaurant Settings",
    {
      fields: ["*"],
    }
  );
  const { call: checkCoupon } = useFrappePostCall(
    "excel_restaurant_pos.api.item.check_coupon_code"
  );
  const { call: getInvoiceGiftCodes } = useFrappePostCall(
    "frappe.client.get_value"
  );
  const taxRate = parseInt(settings?.tax_rate || "0") / 100;

  const textDot = 20; // Set the max character limit before truncating the item name

  const subTotal = orderItems?.reduce(
    (acc: number, item: any) => acc + Number(item.rate) * item.qty,
    0
  );

  const handleIncrement = (name: string) => {
    // find this items index
    const index = orderItems.findIndex((item: any) => item.name === name);
    if (index !== -1) {
      const updatedItems = [...orderItems];
      updatedItems[index].qty
        ? (updatedItems[index].qty += 1)
        : (updatedItems[index].qty = 1);
      setOrderItems(updatedItems);
    }
  };
  const handleDecrement = (name: string) => {
    // find this items index
    const index = orderItems.findIndex((item: any) => item.name === name);
    if (index !== -1) {
      const updatedItems = [...orderItems];
      updatedItems[index].qty && updatedItems[index].qty > 1
        ? (updatedItems[index].qty -= 1)
        : (updatedItems[index].qty = 1);
      setOrderItems(updatedItems);
    }
  };
  const removeItem = (name: string) => {
    const updatedItems = orderItems.filter((item: any) => item.name !== name);
    setOrderItems(updatedItems);
  };

  const handleDiscountChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;

    // Validate the discount value based on the type
    if (discountType === "percentage") {
      const numericValue = Number(value);
      const percentAmount = subTotal * (Number(value) / 100);
      if (value && (numericValue < 0 || numericValue > 100)) {
        setDiscountError("Discount must be between 0 and 100.");
        return;
      }

      if (percentAmount >= subTotal) {
        setDiscountError("Discount cannot be greater than the total amount.");
        return;
      } else {
        setDiscountError("");
        setDiscount(value);
        return;
      }
    }

    if (discountType === "flat") {
      // For flat amount, you can customize your validation logic as needed
      if (value && Number(value) < 0) {
        setDiscountError("Flat discount cannot be negative.");
      } else if (Number(value) > discountLimit) {
        setDiscountError(`Discount cannot be greater than ${discountLimit}.`);
        return;
      } else if (Number(value) >= subTotal) {
        setDiscountError("Discount cannot be greater than the total amount.");
        return;
      } else {
        setDiscountError("");
        setDiscount(value);
      }
    } else {
      setDiscountError("");
      setDiscount("");
    }
  };

  const handleCouponChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCoupon(e.target.value);
  };

  const getDiscountPlaceholder = () => {
    switch (discountType) {
      case "percentage":
        return "percentage";
      case "flat":
        return "flat amount";
      case "coupon":
        return "coupon code";
      default:
        return "";
    }
  };
  const handleDiscountTypeChange = (
    e: React.ChangeEvent<HTMLSelectElement>
  ) => {
    setDiscountType(e.target.value as "flat" | "percentage" | "coupon");

    setDiscount("");
    setDiscountError("");
  };

  const handlePercelChange = (name: string) => {
    const index = orderItems.findIndex((item: any) => item.name === name);
    if (index !== -1) {
      const updatedItems = [...orderItems];
      updatedItems[index].is_parcel = !updatedItems[index].is_parcel;
      setOrderItems(updatedItems);
    }
  };

  // Payment methods management
  const addPaymentMethod = () => {
    // Find available payment methods that haven't been selected yet
    const usedMethods = paymentMethods.map(pm => pm.method);
    const availableMethods = mode_of_payment_list?.filter(
      (method: string) => !usedMethods.includes(method)
    ) || [];

    if (availableMethods.length === 0) {
      toast.error("All payment methods are already added");
      return;
    }

    const newPayment: PaymentMethod = {
      id: Date.now().toString(),
      method: availableMethods[0], // Use the first available method
      amount: "0",
    };
    setPaymentMethods([...paymentMethods, newPayment]);
  };

  const removePaymentMethod = (id: string) => {
    setPaymentMethods(paymentMethods.filter((pm) => pm.id !== id));
  };

  const updatePaymentMethod = (
    id: string,
    field: keyof PaymentMethod,
    value: string
  ) => {
    // If updating the method, check for duplicates
    if (field === 'method') {
      const isDuplicate = paymentMethods.some(pm => pm.id !== id && pm.method === value);
      if (isDuplicate) {
        toast.error("This payment method is already added");
        return;
      }
    }

    setPaymentMethods(
      paymentMethods.map((pm) =>
        pm.id === id ? { ...pm, [field]: value } : pm
      )
    );
  };

  const distributeAmountEvenly = () => {
    if (paymentMethods.length === 0) return;
    const amountPerMethod = payableAmount / paymentMethods.length;
    setPaymentMethods(
      paymentMethods.map((pm) => ({
        ...pm,
        amount: amountPerMethod.toString(),
      }))
    );
  };

  // const setRemainingAmount = () => {
  //   if (paymentMethods.length === 0) return;
  //   const remaining = getRemainingAmount();
  //   if (remaining > 0) {
  //     // Find the first payment method with amount 0 or the last one
  //     const targetIndex = paymentMethods.findIndex(pm => Number(pm.amount) === 0) || paymentMethods.length - 1;
  //     const updatedMethods = [...paymentMethods];
  //     updatedMethods[targetIndex] = { ...updatedMethods[targetIndex], amount: remaining.toString() };
  //     setPaymentMethods(updatedMethods);
  //   }
  // };

  const getTotalPaymentAmount = () => {
    return paymentMethods.reduce((total, pm) => total + Number(pm.amount), 0);
  };

  const getRemainingAmount = () => {
    return payableAmount - getTotalPaymentAmount();
  };
  const { mutate: mutateSalesInvoice } = useFrappeGetDoc("Table Order", orderId, {
    fields: ["sales_invoice"],
  });

  const handleDirectCheckout = () => {
    // Check if this is a credit sale
    const isCreditSale =
      order?.credit_sales === 1 || order?.credit_sales === true;

    // Validate payment methods only for non-credit sales
    if (!isCreditSale && paymentMethods.length > 0) {
      const totalPayment = getTotalPaymentAmount();
      const remaining = getRemainingAmount();

      if (Math.abs(remaining) > 0.01) {
        // Allow for small rounding differences
        toast.error(
          `Payment total (৳${totalPayment.toFixed(
            2
          )}) must equal payable amount (৳${payableAmount.toFixed(2)})`
        );
        return;
      }
    }

    const payload = {
      item_list: orderItems,
      discount: checkDiscount,
      discount_type: discountType,
      status: "Completed",
      is_paid: isCreditSale ? 0 : 1,
      payment_methods:
        !isCreditSale && paymentMethods.length > 0 ? paymentMethods : [],
    };

    console.log({ paymentMethods });
    console.log({ payload });

    // return toast.error("Hold on, processing checkout...");
    startLoading();

    updateDoc("Table Order", orderId, payload)
      .then((res) => {
        if (res) {
          toast.success(
            isCreditSale
              ? "Credit order updated successfully!"
              : "Order completed successfully!"
          );
          closeModal();
          mutate()
          console.log("res", res);
          if (res?.name) {
            // get sales invoice + any generated gift codes
            mutateSalesInvoice().then((data) => {
              if (data?.sales_invoice) {
                handleSalesInvoicePrint(data?.sales_invoice);
                getInvoiceGiftCodes({
                  doctype: "Sales Invoice",
                  filters: { name: data.sales_invoice },
                  fieldname: "custom_generated_gift_cards",
                })
                  .then((r: any) => {
                    const codes = r?.message?.custom_generated_gift_cards;
                    if (codes) {
                      toast.success(`Gift cards: ${codes}`, { duration: 8000 });
                    }
                  })
                  .catch(() => undefined);
              }
            });
          }
        }
      })
      .catch((error) => {
        toast.error("Error updating order status.");
        console.log("Error updating order status:", error);
      })
      .finally(() => {
        stopLoading();
      });
    console.log({ payload });
  };
  const verifyCoupon = () => {
    if (coupon) {
      startLoading();
      checkCoupon({ data: { coupon_code: coupon } })
        .then((res) => {
          if (res?.message?.status === "success") {
            console.log("res", res?.message);
            setDiscountError("");
            discountAmount =
              res?.message?.discount_type === "percentage"
                ? (subTotal * Number(res?.message?.amount ?? 0)) / 100
                : Number(res?.message?.amount ?? 0);
            setDiscount(String(discountAmount));
            setCoupon("");
          } else {
            setDiscountError(res?.message?.message);
            setDiscount("");
          }
        })
        .finally(() => {
          stopLoading();
        });
    }
  };
  let discountAmount =
    discountType === "percentage"
      ? (subTotal * Number(discount)) / 100 > discountLimit
        ? discountLimit
        : (subTotal * Number(discount)) / 100
      : Number(discount);
  const checkDiscount = discountAmount > 0 ? discountAmount : order?.discount;
  const tax = (subTotal - checkDiscount) * taxRate;
  const payableAmount = subTotal - checkDiscount + tax;
  // Functions to calculate totals
  console.log({ orderItems });
  useEffect(() => {
    if (order) {
      setOrderItems(order?.item_list);
    }
  }, [order]);

  // Initialize with a default cash payment method when order loads (only for non-credit sales)
  useEffect(() => {
    if (
      order &&
      paymentMethods.length === 0 &&
      !(order?.credit_sales === 1 || order?.credit_sales === true)
    ) {
      setPaymentMethods([
        {
          id: Date.now().toString(),
          method: "Cash",
          amount: "0",
        },
      ]);
    }
  }, [order, paymentMethods.length]);

  useEffect(() => {
    const setRoleDiscount = (role: string) => {
      if (settings?.discount_allocation) {
        // Find the discount allocation for the specific role
        const discount = settings?.discount_allocation?.find(
          (allocation: any) => allocation?.role === role
        );

        // If a discount exists and has a non-zero amount, set the discount limit
        if (discount && discount?.amount > 0) {
          setDiscountLimit(discount?.amount);
          return true; // Indicate that a discount has been set
        }
      }
      return false; // No discount set for this role
    };

    if (
      userRoles?.includes("Restaurant Manager") &&
      setRoleDiscount("Restaurant Manager")
    ) {
      return; // Exit early if the discount for Restaurant Manager is set
    }

    if (
      userRoles?.includes("Restaurant Cashier") &&
      setRoleDiscount("Restaurant Cashier")
    ) {
      return; // Exit early if the discount for Restaurant Cashier is set
    }

    if (
      userRoles?.includes("Restaurant Waiter") &&
      setRoleDiscount("Restaurant Waiter")
    ) {
      return; // Exit early if the discount for Restaurant Waiter is set
    }
  }, [userRoles, settings?.discount_allocation]);

  // Get available payment methods for a specific payment row
  const getAvailablePaymentMethods = (currentPaymentId: string) => {
    const usedMethods = paymentMethods
      .filter(pm => pm.id !== currentPaymentId)
      .map(pm => pm.method);

    return mode_of_payment_list?.filter(
      (method: string) => !usedMethods.includes(method)
    ) || [];
  };

  return (
    <div
      className="fixed inset-0 flex justify-center items-center bg-black bg-opacity-50 p-2"
      style={{ zIndex: 999 }}
    >
      <div className="bg-white p-2 px-4 pb-3 rounded-md shadow-lg w-96 md:w-[600px] max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-3">
          <div>
            <h1 className="text-base md:text-lg font-semibold mb-2">
              Cart Summary
            </h1>
            {(order?.credit_sales === 1 || order?.credit_sales === true) && (
              <span className="text-xs bg-orange-100 text-orange-800 px-2 py-1 rounded-full">
                Credit Sale
              </span>
            )}
          </div>
          <button
            onClick={closeModal}
            className="text-red-500 text-xs md:text-sm border rounded-md p-1"
          >
            <RxCross2 />
          </button>
        </div>
        {orderItems?.length > 0 ? (
          <div className="text-xs md:text-sm">
            {orderItems?.map((item: any) => (
              <div className="accordion mb-1" key={item?.name}>
                <div className="border rounded-md p-2">
                  <div className="flex justify-between items-center transition font-medium">
                    <div className="block w-1/3">
                      <p title={item?.item} className="font-semibold truncate">
                        {(item?.item ?? "").substring(0, textDot)}
                        {item?.item_name?.length > textDot ? "..." : ""}
                      </p>
                      <p className="font-semibold mt-1">৳{item?.rate}</p>

                      <div className="flex items-center space-x-2 mt-1">
                        <label className="flex items-center text-xs">
                          <input
                            type="checkbox"
                            checked={item?.is_parcel}
                            className="mr-2"
                            onChange={() => handlePercelChange(item?.name)}
                          />
                          Takeaway
                        </label>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <div className="flex items-center rounded-md h-fit border w-full">
                        <button
                          onClick={() => handleDecrement(item?.name)}
                          className="px-2 rounded-md rounded-e-none text-xs bg-gray-200 h-fit py-1.5"
                        >
                          <LuMinus className="text-xs" />
                        </button>
                        <span className="px-2 text-xs h-full flex items-center">
                          {item?.qty}
                        </span>
                        <button
                          onClick={() => handleIncrement(item?.name)}
                          className="px-2 rounded-md rounded-s-none bg-gray-200 h-fit py-1.5"
                        >
                          <FiPlus className="text-xs" />
                        </button>
                      </div>
                      <button
                        onClick={() => removeItem(item?.name)}
                        className="text-red-500 px-2 rounded-md text-xs bg-gray-200 h-fit py-1.5 border"
                      >
                        <AiTwotoneDelete />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center min-h-28 border border-borderColor rounded-md text-xs">
            No item in cart
          </div>
        )}

        <div className="py-4 flex flex-col items-start">
          <h3 className="font-semibold text-sm mb-1">Discount</h3>
          {order?.discount > 0 && (
            <p className="text-xs text-green-500">
              Applied: ৳{order?.discount}
            </p>
          )}
          <div className="flex gap-2 w-full text-sm relative">
            <select
              value={discountType}
              onChange={handleDiscountTypeChange}
              className="border rounded-md p-1 focus:outline-none px-2"
            >
              <option value="percentage">Percentage</option>
              <option value="flat">Flat Amount</option>
              <option value="coupon">Coupon</option>
            </select>
            <input
              type={discountType === "coupon" ? "text" : "number"}
              value={discountType === "coupon" ? coupon : discount}
              onChange={
                discountType === "coupon"
                  ? handleCouponChange
                  : handleDiscountChange
              }
              className={`border rounded-md p-1 focus:outline-none px-3 w-full ${discountError ? "border-red-500" : ""
                }`}
              placeholder={`Enter ${getDiscountPlaceholder()}`}
            />
            {discountError && (
              <p className="text-red-500 text-xs right-0 -bottom-5 pt-2 absolute">
                {discountError}
              </p>
            )}
            {discountType === "coupon" && (
              <button
                onClick={verifyCoupon}
                className="absolute right-3 top-1  px-2 py-1 bg-blue-500 text-xs text-white rounded-md hover:bg-blue-600"
              >
                Verify
              </button>
            )}
          </div>
          <GiftCardRedeemPanel
            salesInvoice={order?.sales_invoice}
            promoCouponActive={discountType === "coupon" && Boolean(coupon)}
            onAppliedChange={(_rows, discountTotal) => {
              if (discountTotal > 0) {
                setDiscountType("flat");
                setDiscount(String(discountTotal));
                setCoupon("");
              }
            }}
          />
        </div>

        {/* Checkout details */}
        <div className="p-3 border rounded-md mt-5">
          <div className="flex justify-between text-xs md:text-sm">
            <h1>Subtotal</h1>
            <h1>৳{subTotal.toFixed(2)}</h1>
          </div>
          <div className="flex justify-between text-xs md:text-sm mt-2">
            <h1>Discount</h1>
            <h1>
              ৳
              {discountAmount > 0
                ? discountAmount?.toFixed(2)
                : order?.discount}
            </h1>
          </div>
          <div className="flex justify-between text-xs md:text-sm mt-2">
            <h1>Tax ({taxRate * 100}%)</h1>
            <h1>৳{tax.toFixed(2)}</h1>
          </div>
          <div className="flex justify-between text-xs md:text-sm font-semibold mt-2">
            <h1>Payable Amount</h1>
            <h1>৳{payableAmount ? payableAmount : order?.total_amount}</h1>
          </div>
        </div>

        {/* Payment Methods - Only show for non-credit sales */}
        {!(order?.credit_sales === 1 || order?.credit_sales === true) && (
          <div className="mt-5">
            <div className="xs:flex justify-between items-center mb-3">
              <h3 className="font-semibold text-sm mb-2 sm:mb-0">Payment Methods</h3>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={distributeAmountEvenly}
                  className="text-xs bg-blue-500 text-white px-2 py-1 rounded hover:bg-blue-600"
                  disabled={paymentMethods.length === 0}
                >
                  Distribute Evenly
                </button>
                <button
                  onClick={addPaymentMethod}
                  className="text-xs bg-green-500 text-white px-2 py-1 rounded hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={paymentMethods.length >= (mode_of_payment_list?.length || 0)}
                >
                  Add Payment
                </button>
              </div>
            </div>

            {paymentMethods?.length > 0 && (
              <div className="border rounded-md p-3">
                <div className="space-y-2">
                  {paymentMethods?.map((payment) => (
                    <div
                      key={payment.id}
                      className="flex flex-col md:flex-row md:items-center gap-2 border-b pb-2 last:border-0"
                    >
                      {/* Select - Full width on mobile, flexible on larger screens */}
                      <select
                        value={payment.method}
                        onChange={(e) =>
                          updatePaymentMethod(
                            payment.id,
                            "method",
                            e.target.value
                          )
                        }
                        className="text-xs border rounded px-2 py-1 w-full md:flex-1 focus:outline-none"
                      >
                        {getAvailablePaymentMethods(payment.id)?.map((item: any) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>

                      {/* Inputs container - will wrap to second line on mobile */}
                      <div className="flex flex-1 items-center gap-2 w-full">
                        <input
                          type="text"
                          value={payment.reference || ""}
                          onChange={(e) =>
                            updatePaymentMethod(
                              payment.id,
                              "reference",
                              e.target.value
                            )
                          }
                          className="text-xs border rounded px-2 py-1.5 flex-1 md:w-40 focus:outline-none"
                          placeholder="Type Reference Number"
                        />
                        <input
                          type="number"
                          min={0}
                          value={payment.amount.toString()}
                          onChange={(e) =>
                            updatePaymentMethod(
                              payment.id,
                              "amount",
                              e.target.value
                            )
                          }
                          className="text-xs border rounded px-2 py-1.5 w-20 focus:outline-none"
                          placeholder="Amount"
                        />
                        <button
                          onClick={() => removePaymentMethod(payment.id)}
                          className="text-red-500 text-xs px-2 py-1.5 border rounded hover:bg-red-50 flex-shrink-0"
                        >
                          <AiTwotoneDelete />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-3 pt-2 border-t">
                  <div className="flex justify-between text-xs">
                    <span>Total Payment:</span>
                    <span className="font-semibold">
                      ৳{getTotalPaymentAmount().toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs mt-1">
                    <span>Remaining:</span>
                    <span
                      className={`font-semibold ${getRemainingAmount() > 0
                        ? "text-red-500"
                        : getRemainingAmount() < 0
                          ? "text-green-500"
                          : "text-gray-500"
                        }`}
                    >
                      ৳{getRemainingAmount().toFixed(2)}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-between gap-3 ">
          <button
            onClick={closeModal}
            className="bg-primaryColor text-white w-full p-2 rounded-md mt-3 text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleDirectCheckout}
            className="bg-primaryColor text-white w-full p-2 rounded-md mt-3 text-sm flex items-center justify-center gap-1.5"
            disabled={isLoading}
          >
            {isLoading && <CgSpinner className="animate-spin" />}
            {isLoading
              ? "Loading..."
              : order?.credit_sales === 1 || order?.credit_sales === true
                ? "Update Credit Order"
                : "Checkout"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SingleOrderModal;
