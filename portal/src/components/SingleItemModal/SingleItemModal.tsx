import { useFrappeGetCall } from "frappe-react-sdk";
import { memo, useCallback, useEffect, useState } from "react";
import { FiMinus, FiPlus } from "react-icons/fi";
import { RxCross2 } from "react-icons/rx";
import { useCartContext } from "../../context/cartContext";
import { Food } from "../../data/items";
import GiftCardSellFields, {
  GiftCardSellState,
} from "../GiftCard/GiftCardSellFields";
import AddOnsItemCard from "./components/AddOnsItemCard";

type Props = {
  isOpen: boolean;
  toggleDrawer: () => void;
  selectedItem: Food | null;
};

type DrawerProps = {
  isOpen: boolean;
  isLargeDevice: boolean;
  children: React.ReactNode;
};

// Memoize the ItemsDrawer to prevent unnecessary re-renders
const ItemsDrawer = memo(({ children, isOpen, isLargeDevice }: DrawerProps) => {
  if (isLargeDevice) {
    return (
      <div
        className={`fixed top-0 left-0 inset-0 z-50 flex items-center justify-center p-4 overflow-x-hidden ${isOpen ? "bg-black bg-opacity-50" : "hidden"}`}
        style={{ zIndex: 999 }}
      >
        <div
          className={`bg-white rounded-lg shadow-lg transition-transform duration-500 ease-in-out ${isOpen ? "scale-100" : "scale-0"} md:max-w-lg w-full h-auto`}
        >
          {children}
        </div>
      </div>
    );
  } else {
    return (
      <div className="h-[100vh] w-full" style={{ zIndex: 999 }}>
        <div
          className={`drawer-bottom bg-white shadow-lg transition-transform duration-500 ease-in-out z-50 ${isOpen ? "translate-y-0" : "translate-y-full"} fixed bottom-0 left-0 w-full min-h-[100%]`}
          style={{ zIndex: 999 }}
        >
          {children}
        </div>
      </div>
    );
  }
});

const SingleItemModal = ({ isOpen, toggleDrawer, selectedItem }: Props) => {
  const { data: item } = useFrappeGetCall(`excel_restaurant_pos.api.item.get_single_food_item_details?item_code=${selectedItem}`, { fields: ["*"] });
  const itemDetails = item?.message;
  console.log("itemDetails", itemDetails);
  const {updateCartCount} = useCartContext()

  const [selectedVariation, setSelectedVariation] = useState({});
  const [quantity, setQuantity] = useState(1);
  const [selectedItems, setSelectedItems] = useState<Food[]>([]);
  const [isLargeDevice, setIsLargeDevice] = useState(window.innerWidth > 768);
  const [selectedAddOns, setSelectedAddOns] = useState<Food[]>([]);
  const [giftCard, setGiftCard] = useState<GiftCardSellState>({
    custom_is_gift_card_item: 0,
    custom_gift_card_type: "New",
    custom_gift_amount: 0,
  });
  const handleAddOnsChange = (item: Food) => {
    // console.log("item", item);
    setSelectedAddOns(prevAddOns =>
        prevAddOns.some(addOn => addOn.item_code === item.item_code)
            ? prevAddOns.filter(addOn => addOn.item_code !== item.item_code)  // Remove if already selected
            : [...prevAddOns, { ...item, quantity: 1 }]          // Add with quantity 1 if not selected
    );
};
const calculateTotalPrice = () => {
  // Base item price
  const basePrice = selectedVariation.price || itemDetails?.price || 0;
  const itemTotal = basePrice * quantity;

  // Add-ons total
  const addOnsTotal = selectedAddOns.reduce((total, addOn) => {
    return total + (addOn.price || 0) * addOn.quantity;
  }, 0);

  // Sum base item total and add-ons total
  return itemTotal + addOnsTotal;
};
// Inside the SingleItemModal component

const increment = () => {
  setQuantity(prevQuantity => prevQuantity + 1);
};

const decrement = () => {
  setQuantity(prevQuantity => (prevQuantity > 1 ? prevQuantity - 1 : 1));
};


const incrementAddOns = (item_code: string) => {
    setSelectedAddOns(prevAddOns =>
        prevAddOns.map(addOn =>
            addOn?.item_code === item_code ? { ...addOn, quantity: addOn?.quantity + 1 } : addOn
        )
    );
};

const decrementAddOns = (item_code: string) => {
    setSelectedAddOns(prevAddOns =>
        prevAddOns.map(addOn =>
            addOn?.item_code === item_code && addOn.quantity > 1 ? { ...addOn, quantity: addOn.quantity - 1 } : addOn
        )
    );
};

const addToCart = () => {
  const isGift = Boolean(itemDetails?.custom_is_gift_card_item);
  if (isGift && giftCard.custom_gift_card_type === "Existing" && !giftCard.custom_gift_card_code) {
    alert("Select an Inactive gift card code for Existing type.");
    return;
  }

  const giftFields = isGift
    ? {
        custom_is_gift_card_item: 1,
        custom_gift_card_type: giftCard.custom_gift_card_type,
        custom_gift_card_code: giftCard.custom_gift_card_code,
        custom_gift_amount:
          giftCard.custom_gift_amount || itemDetails?.custom_gift_card_value || 0,
        price:
          giftCard.custom_gift_amount ||
          itemDetails?.custom_gift_card_value ||
          selectedVariation?.price ||
          itemDetails?.price,
      }
    : {};

  const newCartItem = [
    { ...selectedVariation, quantity, ...giftFields },
    ...selectedAddOns,
  ];
      // return;
  // Retrieve the existing cart from local storage
  const existingCart = JSON.parse(localStorage.getItem("cart")) || [];

  // Combine existing cart and new cart items
  const combinedCart = [...existingCart, ...newCartItem];

  // Use a Map to remove duplicates by `item_code` (+ gift code for Existing)
  const uniqueCart = Array.from(
    new Map(
      combinedCart.map((item) => [
        item?.custom_gift_card_code
          ? `${item?.item_code}::${item.custom_gift_card_code}`
          : item?.item_code,
        item,
      ])
    ).values()
  );

  // If a new item was added, save to local storage and show success toast
  
  if (uniqueCart.length >= existingCart.length) {
    console.log("uniqueCart", uniqueCart);
    localStorage.setItem("cart", JSON.stringify(uniqueCart));
    // toast.success("Item added to cart!");
    updateCartCount()
  }
  setQuantity(1); // Reset quantity to 1
  setSelectedVariation({}); // Reset selected variation
  setSelectedAddOns([]); // Clear selected add-ons
  setGiftCard({
    custom_is_gift_card_item: 0,
    custom_gift_card_type: "New",
    custom_gift_amount: 0,
  });
  toggleDrawer();

 
};
const getDescription = (description: string) => {
  const hasHtml = (text) => /<\/?[a-z][\s\S]*>/i.test(text);
  const stripHtml = (html) => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return doc.body.textContent || "";
  };
  const cleanContent = hasHtml(description) ? stripHtml(description) : description;
  return cleanContent;
}


  useEffect(() => {
    const handleResize = () => {
      setIsLargeDevice(window.innerWidth > 768);
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Close handler with memoization to avoid recreating it on each render
  const closeHandler = useCallback(() => {
    setQuantity(1);
    setSelectedItems([]);
    toggleDrawer();
  }, [toggleDrawer]);

  useEffect(() => {
    if (isOpen && itemDetails?.has_variants) {
      const defaultVariant = itemDetails?.variant_item_list?.find((variation:any) => variation.default_variant);
      if (defaultVariant) {
        setSelectedVariation(defaultVariant);
       
      }
      else{
        setSelectedVariation(itemDetails?.variant_item_list[0])
      }
    }else{
      setSelectedVariation({
        item_code: itemDetails?.item_code,
        item_name: itemDetails?.item_name,
        image: itemDetails?.image,
        price: itemDetails?.price,
      })
     
    }
  }, [isOpen, itemDetails]);

  return (
    <>
      <ItemsDrawer isOpen={isOpen} isLargeDevice={isLargeDevice}>
        <div className={`overflow-y-auto ${isLargeDevice ? "max-h-[calc(100vh-100px)] pb-28" : "max-h-[100vh] pb-24"}`}>
          <div className="mb-3">
            <img
              src={itemDetails?.image || "https://images.deliveryhero.io/image/fd-bd/Products/5331721.jpg??width=400"}
              alt=""
              className="h-auto max-h-[220px] lg:max-h-[280px] w-full object-cover rounded-b-lg md:rounded-t-lg shadow-lg"
            />
          </div>
          <div className="p-4">
            <div className="flex justify-end fixed top-5 right-7 z-50">
              <button className="bg-gray-50 h-8 w-8 border rounded-full mb-3 flex items-center justify-center" onClick={closeHandler}>
                <RxCross2 />
              </button>
            </div>
            <div>
              <h2 className="font-semibold">{itemDetails?.item_name}</h2>
              <h2 className="text-xs font-semibold pt-1">Price ৳{itemDetails?.price}</h2>
              <h2 className="text-xs text-gray-500 pt-2">{getDescription(itemDetails?.description)}</h2>
            </div>
            {itemDetails?.has_variants && (
              <div className="border shadow p-2 rounded-md mt-4">
                <h2 className="mb-3 text-xs font-semibold">Variation</h2>
                {itemDetails?.variant_item_list?.map((variation) => (
                  <label key={variation?.item_code} className="flex justify-between mb-3 text-xs capitalize">
                    <div className="flex items-center">
                      <input
                        type="radio"
                        value={variation?.item_code}
                        checked={variation?.item_code === selectedVariation?.item_code}
                        onChange={() => setSelectedVariation(variation)}
                        className="mr-2"
                      />
                      {variation?.item_name}
                    </div>
                    <h2>{variation?.price}</h2>
                  </label>
                ))}
              </div>
            )}
              {itemDetails?.add_ons_item_list?.length > 0 && (
                    <>
                      {/* Add Ons Header */}
                      <h2 className="mt-4 text-[13px] font-semibold flex justify-between items-center">
                        <p>Add Ons</p>
                        <p className="text-gray-500 text-xs">(Optional)</p>
                      </h2>
                      <p className="mb-3 mt-1 text-xs">Select add ons</p>

                      {/* Render Add Ons Items */}
                      {itemDetails?.add_ons_item_list?.slice(0, 5)?.map((item, index) => (
                        <AddOnsItemCard
                          key={index}
                          item={item}
                          handleAddOnsChange={handleAddOnsChange}
                          selectedItems={selectedAddOns}
                          decrementAddOns={decrementAddOns}
                          incrementAddOns={incrementAddOns}
                        />
                      ))}
                    </>
                  )}

            <GiftCardSellFields
              isGiftCardItem={Boolean(itemDetails?.custom_is_gift_card_item)}
              giftCardValue={Number(itemDetails?.custom_gift_card_value || 0)}
              value={giftCard}
              onChange={setGiftCard}
            />

            {/* Other optional sections like Add-ons */}
          </div>
        </div>
        <div className={`p-4 pt-2 border bottom-0 absolute w-full bg-white z-50 ${isLargeDevice ? "rounded-b-lg" : ""}`}>
          <div className="flex justify-between items-center">
          <div className="flex items-center border rounded-md text-sm bg-gray-100">
            <button
              onClick={decrement}
              className="px-4 py-2 rounded-l-md text-base bg-gray-300 transition-colors duration-200 hover:bg-gray-400 focus:outline-none"
            >
              <FiMinus className="text-xs md:text-sm" />
            </button>
            <span className="px-4 text-gray-800 font-medium">{quantity}</span>
            <button
              onClick={increment}
              className="px-4 py-2 rounded-r-md text-xs md:text-sm bg-gray-300 transition-colors duration-200 hover:bg-gray-400 focus:outline-none"
            >
              <FiPlus />
            </button>
          </div>

            <div className="text-sm font-semibold">Total: ৳{calculateTotalPrice()}</div>

            <button onClick={()=> addToCart()} className="bg-primaryColor px-3 py-1.5 rounded-md text-white h-fit text-xs md:text-sm">
              Add to cart
            </button>
          </div>
        </div>
      </ItemsDrawer>
    </>
  );
};

export default memo(SingleItemModal);
