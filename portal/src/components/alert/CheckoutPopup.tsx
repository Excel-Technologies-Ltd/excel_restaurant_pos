type Props = {
  handleClosePopup: () => void;
  generatedGiftCards?: string;
};

const CheckoutPopup = ({ handleClosePopup, generatedGiftCards }: Props) => {
  const codes = (generatedGiftCards || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50 px-4"
      style={{ zIndex: 999 }}
    >
      <div className="bg-white p-4 rounded-lg shadow-lg max-w-sm w-full relative">
        <h2 className="text-lg font-semibold text-center">
          Checkout Successful!
        </h2>
        <p className="text-sm text-gray-600 mt-2 text-center">
          Your order has been placed successfully.
        </p>
        {codes.length > 0 && (
          <div className="mt-3 p-2 bg-gray-50 rounded text-sm">
            <p className="font-semibold text-center mb-1">Generated Gift Cards</p>
            <ul className="space-y-1 text-center font-mono text-xs break-all">
              {codes.map((code) => (
                <li key={code}>{code}</li>
              ))}
            </ul>
            <button
              type="button"
              className="w-full mt-2 text-xs underline text-primaryColor"
              onClick={() => navigator.clipboard?.writeText(codes.join(", "))}
            >
              Copy codes
            </button>
          </div>
        )}
        <div className="text-center">
          <button
            onClick={handleClosePopup}
            className="bg-primaryColor text-white p-2 px-4 mt-4 rounded-md"
          >
            Ok
          </button>
        </div>
      </div>
    </div>
  );
};

export default CheckoutPopup;
