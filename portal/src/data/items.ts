import { Variation } from "../components/ItemList/ItemList";
import { Item } from "../components/models/Item";

export interface Food {
  id?: number;
  item_name?: string;
  item_code?: string;
  description?: string;
  regularPrice?: number;
  price?: number;
  image?: string;
  quantity?: number;
  variation?: Variation[];
  addOns?: Food[];
  relatedItems?: Food[];
  categoryId?: number;
  is_add_on?: boolean;
  isComplimentary?: boolean;
  custom_is_gift_card_item?: number;
  custom_gift_card_type?: "New" | "Existing";
  custom_gift_card_code?: string;
  custom_gift_amount?: number;
}

export const foods: Food[] = [
  {
    id: 1,
    name: "Mutton Biriyani",
    description: "Aromatic biriyani with tender mutton pieces.",
    regularPrice: 400,
    sellPrice: 380,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/1789871.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 380,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 250,
      },
      {
        id: 3,
        name: "full",
        price: 700,
      },
    ],
    addOns: [
      {
        id: 101,
        name: "More Cheese",
        sellPrice: 50,
        is_add_on: true,
      },
      {
        id: 102,
        name: "More Naga",
        sellPrice: 20,
      },
      {
        id: 103,
        name: "Extra Patty - Chicken",
        sellPrice: 119,
      },
      {
        id: 104,
        name: "Extra Patty - Mutton",
        sellPrice: 149,
      },
    ],
    relatedItems: [
      {
        id: 2,
        name: "Kacchi Biriyani",
        sellPrice: 450,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 2,
    name: "Kacchi Biriyani",
    description: "Flavorful Kacchi biriyani with perfectly cooked meat.",
    regularPrice: 500,
    sellPrice: 450,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/4746830.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 450,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 300,
      },
      {
        id: 3,
        name: "full",
        price: 800,
      },
    ],
    addOns: [
      {
        id: 201,
        name: "More Cheese",
        sellPrice: 50,
      },
      {
        id: 202,
        name: "More Naga",
        sellPrice: 20,
      },
      {
        id: 203,
        name: "Extra Patty - Chicken",
        sellPrice: 119,
      },
      {
        id: 204,
        name: "Extra Patty - Mutton",
        sellPrice: 149,
      },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 2,
  },
  {
    id: 3,
    name: "Chicken Grilled",
    description: "Tender grilled chicken with herbs and spices.",
    regularPrice: 300,
    sellPrice: 280,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6129877.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 280,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 180,
      },
      {
        id: 3,
        name: "full",
        price: 550,
      },
    ],
    addOns: [
      {
        id: 301,
        name: "More Cheese",
        sellPrice: 39,
      },
      {
        id: 302,
        name: "More Sauce",
        sellPrice: 29,
      },
      {
        id: 303,
        name: "Extra Patty - Chicken",
        sellPrice: 119,
      },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 3,
  },
  {
    id: 4,
    name: "Pepperoni Pizza",
    description: "Classic pepperoni pizza with hand-tossed crust.",
    regularPrice: 500,
    sellPrice: 480,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/Cheez/3092955.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 480,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 320,
      },
      {
        id: 3,
        name: "full",
        price: 950,
      },
    ],
    addOns: [
      {
        id: 401,
        name: "More Cheese",
        sellPrice: 50,
      },
      {
        id: 402,
        name: "More Sauce",
        sellPrice: 29,
      },
      {
        id: 403,
        name: "Extra Toppings",
        sellPrice: 99,
      },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 4,
  },
  {
    id: 5,
    name: "Mutton Burger",
    description: "Juicy Mutton burger with lettuce, tomato, and cheese.",
    regularPrice: 350,
    sellPrice: 320,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/8246710.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 320,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 200,
      },
      {
        id: 3,
        name: "full",
        price: 600,
      },
    ],
    addOns: [
      {
        id: 501,
        name: "Extra Patty",
        sellPrice: 119,
      },
      {
        id: 502,
        name: "More Cheese",
        sellPrice: 50,
      },
      {
        id: 503,
        name: "Extra Sauce",
        sellPrice: 29,
      },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 5,
  },
  {
    id: 6,
    name: "Spaghetti Carbonara",
    description: "Italian spaghetti with creamy carbonara sauce.",
    regularPrice: 420,
    sellPrice: 400,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3799616.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 400,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 300,
      },
      {
        id: 3,
        name: "full",
        price: 750,
      },
    ],
    addOns: [
      {
        id: 601,
        name: "Extra Sauce",
        sellPrice: 29,
        is_add_on: true,
      },
      {
        id: 602,
        name: "More Cheese",
        sellPrice: 50,
        is_add_on: true,
      },
    ],
    relatedItems: [
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 6,
  },
  {
    id: 7,
    name: "Caesar Salad",
    description: "Classic Caesar salad with croutons and dressing.",
    regularPrice: 280,
    sellPrice: 250,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6273458.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 250,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 180,
      },
      {
        id: 3,
        name: "full",
        price: 500,
      },
    ],
    addOns: [
      {
        id: 701,
        name: "Extra Croutons",
        sellPrice: 20,
        is_add_on: true,
      },
      {
        id: 702,
        name: "More Dressing",
        sellPrice: 15,
      },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 7,
  },
  {
    id: 8,
    name: "Salmon Sushi Roll",
    description: "Fresh salmon sushi roll with wasabi and soy sauce.",
    regularPrice: 600,
    sellPrice: 580,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3065733.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 580,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 400,
      },
      {
        id: 3,
        name: "full",
        price: 1200,
      },
    ],
    addOns: [
      {
        id: 801,
        name: "More Wasabi",
        sellPrice: 20,
        is_add_on: true,
      },
      {
        id: 802,
        name: "Extra Soy Sauce",
        sellPrice: 15,
        is_add_on: true,
      },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 8,
  },
  {
    id: 9,
    name: "Grilled Shrimp",
    description: "Grilled shrimp with garlic butter and lemon.",
    regularPrice: 700,
    sellPrice: 680,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3515850.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 680,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 480,
      },
      {
        id: 3,
        name: "full",
        price: 1300,
      },
    ],
    addOns: [
      {
        id: 901,
        name: "Extra Lemon",
        sellPrice: 15,
      },
      {
        id: 902,
        name: "More Garlic Butter",
        sellPrice: 29,
      },
    ],
    relatedItems: [
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 9,
  },
  {
    id: 10,
    name: "T-Bone Steak",
    description: "Grilled T-bone steak with mashed potatoes.",
    regularPrice: 1200,
    sellPrice: 1150,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/8682551.jpg??width=400",
    variation: [
      {
        id: 1,
        name: "half",
        price: 1150,
      },
      {
        id: 2,
        name: "Half Quarter",
        price: 800,
      },
      {
        id: 3,
        name: "full",
        price: 1600,
      },
    ],
    addOns: [
      {
        id: 1001,
        name: "More Mashed Potatoes",
        sellPrice: 50,
      },
      {
        id: 1002,
        name: "Extra Sauce",
        sellPrice: 29,
      },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 10,
  },
  {
    id: 11,
    name: "Mutton Biriyani",
    description: "Aromatic biriyani with tender mutton pieces.",
    regularPrice: 400,
    sellPrice: 380,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6129869.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 380 },
      { id: 2, name: "Half Quarter", price: 250 },
      { id: 3, name: "full", price: 700 },
    ],
    addOns: [
      { id: 1101, name: "More Cheese", sellPrice: 50 },
      { id: 1102, name: "More Naga", sellPrice: 20 },
      { id: 1103, name: "Extra Patty - Chicken", sellPrice: 119 },
      { id: 1104, name: "Extra Patty - Mutton", sellPrice: 149 },
    ],
    relatedItems: [
      {
        id: 2,
        name: "Kacchi Biriyani",
        sellPrice: 450,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 12,
    name: "Kacchi Biriyani",
    description: "Flavorful Kacchi biriyani with perfectly cooked meat.",
    regularPrice: 500,
    sellPrice: 450,
    image: "",
    variation: [
      { id: 1, name: "half", price: 450 },
      { id: 2, name: "Half Quarter", price: 300 },
      { id: 3, name: "full", price: 800 },
    ],
    addOns: [
      { id: 1201, name: "More Cheese", sellPrice: 50 },
      { id: 1202, name: "More Naga", sellPrice: 20 },
      { id: 1203, name: "Extra Patty - Chicken", sellPrice: 119 },
      { id: 1204, name: "Extra Patty - Mutton", sellPrice: 149 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 13,
    name: "Chicken Grilled",
    description: "Tender grilled chicken with herbs and spices.",
    regularPrice: 300,
    sellPrice: 280,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/1873876.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 280 },
      { id: 2, name: "Half Quarter", price: 180 },
      { id: 3, name: "full", price: 550 },
    ],
    addOns: [
      { id: 1301, name: "More Cheese", sellPrice: 39 },
      { id: 1302, name: "More Sauce", sellPrice: 29 },
      { id: 1303, name: "Extra Patty - Chicken", sellPrice: 119 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 3,
  },
  {
    id: 14,
    name: "Pepperoni Pizza",
    description: "Classic pepperoni pizza with hand-tossed crust.",
    regularPrice: 500,
    sellPrice: 480,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/Cheez/3092955.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 480 },
      { id: 2, name: "Half Quarter", price: 320 },
      { id: 3, name: "full", price: 950 },
    ],
    addOns: [
      { id: 1401, name: "More Cheese", sellPrice: 50 },
      { id: 1402, name: "More Sauce", sellPrice: 29 },
      { id: 1403, name: "Extra Toppings", sellPrice: 99 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 15,
    name: "Mutton Burger",
    description: "Juicy Mutton burger with lettuce, tomato, and cheese.",
    regularPrice: 350,
    sellPrice: 320,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/4547350.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 320 },
      { id: 2, name: "Half Quarter", price: 200 },
      { id: 3, name: "full", price: 600 },
    ],
    addOns: [
      { id: 1501, name: "Extra Patty", sellPrice: 119 },
      { id: 1502, name: "More Cheese", sellPrice: 50 },
      { id: 1503, name: "Extra Sauce", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 5,
  },
  {
    id: 16,
    name: "Spaghetti Carbonara",
    description: "Italian spaghetti with creamy carbonara sauce.",
    regularPrice: 420,
    sellPrice: 400,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3799596.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 400 },
      { id: 2, name: "Half Quarter", price: 300 },
      { id: 3, name: "full", price: 750 },
    ],
    addOns: [
      { id: 1601, name: "Extra Sauce", sellPrice: 29 },
      { id: 1602, name: "More Cheese", sellPrice: 50 },
    ],
    relatedItems: [
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 6,
  },
  {
    id: 17,
    name: "Caesar Salad",
    description: "Classic Caesar salad with croutons and dressing.",
    regularPrice: 280,
    sellPrice: 250,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6273450.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 250 },
      { id: 2, name: "Half Quarter", price: 180 },
      { id: 3, name: "full", price: 500 },
    ],
    addOns: [
      { id: 1701, name: "Extra Croutons", sellPrice: 20 },
      { id: 1702, name: "More Dressing", sellPrice: 15 },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 18,
    name: "Salmon Sushi Roll",
    description: "Fresh salmon sushi roll with wasabi and soy sauce.",
    regularPrice: 600,
    sellPrice: 580,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/7986813.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 580 },
      { id: 2, name: "Half Quarter", price: 400 },
      { id: 3, name: "full", price: 1200 },
    ],
    addOns: [
      { id: 1801, name: "More Wasabi", sellPrice: 20 },
      { id: 1802, name: "Extra Soy Sauce", sellPrice: 15 },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 2,
  },
  {
    id: 19,
    name: "Grilled Shrimp",
    description: "Grilled shrimp with garlic butter and lemon.",
    regularPrice: 700,
    sellPrice: 680,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3515850.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 680 },
      { id: 2, name: "Half Quarter", price: 480 },
      { id: 3, name: "full", price: 1300 },
    ],
    addOns: [
      { id: 1901, name: "Extra Lemon", sellPrice: 15 },
      { id: 1902, name: "More Garlic Butter", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 2,
  },
  {
    id: 20,
    name: "T-Bone Steak",
    description: "Grilled T-bone steak with mashed potatoes.",
    regularPrice: 1200,
    sellPrice: 1150,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/8310492.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 1150 },
      { id: 2, name: "Half Quarter", price: 800 },
      { id: 3, name: "full", price: 1600 },
    ],
    addOns: [
      { id: 2001, name: "More Mashed Potatoes", sellPrice: 50 },
      { id: 2002, name: "Extra Sauce", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 10,
  },
  {
    id: 21,
    name: "Mutton Biriyani",
    description: "Aromatic biriyani with tender mutton pieces.",
    regularPrice: 400,
    sellPrice: 380,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/4911940.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 380 },
      { id: 2, name: "Half Quarter", price: 250 },
      { id: 3, name: "full", price: 700 },
    ],
    addOns: [
      { id: 2101, name: "More Cheese", sellPrice: 50, is_add_on: true },
      { id: 2102, name: "More Naga", sellPrice: 20, is_add_on: true },
      {
        id: 2103,
        name: "Extra Patty - Chicken",
        sellPrice: 119,
        is_add_on: true,
      },
      {
        id: 2104,
        name: "Extra Patty - Mutton",
        sellPrice: 149,
        is_add_on: true,
      },
    ],
    relatedItems: [
      {
        id: 2,
        name: "Kacchi Biriyani",
        sellPrice: 450,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 2,
  },
  {
    id: 22,
    name: "Kacchi Biriyani",
    description: "Flavorful Kacchi biriyani with perfectly cooked meat.",
    regularPrice: 500,
    sellPrice: 450,
    image: "",
    variation: [
      { id: 1, name: "half", price: 450 },
      { id: 2, name: "Half Quarter", price: 300 },
      { id: 3, name: "full", price: 800 },
    ],
    addOns: [
      { id: 2201, name: "More Cheese", sellPrice: 50 },
      { id: 2202, name: "More Naga", sellPrice: 20 },
      { id: 2203, name: "Extra Patty - Chicken", sellPrice: 119 },
      { id: 2204, name: "Extra Patty - Mutton", sellPrice: 149 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 23,
    name: "Chicken Grilled",
    description: "Tender grilled chicken with herbs and spices.",
    regularPrice: 300,
    sellPrice: 280,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6129874.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 280 },
      { id: 2, name: "Half Quarter", price: 180 },
      { id: 3, name: "full", price: 550 },
    ],
    addOns: [
      { id: 2301, name: "More Cheese", sellPrice: 39 },
      { id: 2302, name: "More Sauce", sellPrice: 29 },
      { id: 2303, name: "Extra Patty - Chicken", sellPrice: 119 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 3,
  },
  {
    id: 24,
    name: "Pepperoni Pizza",
    description: "Classic pepperoni pizza with hand-tossed crust.",
    regularPrice: 500,
    sellPrice: 480,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/620736.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 480 },
      { id: 2, name: "Half Quarter", price: 320 },
      { id: 3, name: "full", price: 950 },
    ],
    addOns: [
      { id: 2401, name: "More Cheese", sellPrice: 50 },
      { id: 2402, name: "More Sauce", sellPrice: 29 },
      { id: 2403, name: "Extra Toppings", sellPrice: 99 },
    ],
    relatedItems: [
      {
        id: 1,
        name: "Mutton Biriyani",
        sellPrice: 380,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 4,
  },
  {
    id: 25,
    name: "Mutton Burger",
    description: "Juicy Mutton burger with lettuce, tomato, and cheese.",
    regularPrice: 350,
    sellPrice: 320,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/370107.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 320 },
      { id: 2, name: "Half Quarter", price: 200 },
      { id: 3, name: "full", price: 600 },
    ],
    addOns: [
      { id: 2501, name: "Extra Patty", sellPrice: 119 },
      { id: 2502, name: "More Cheese", sellPrice: 50 },
      { id: 2503, name: "Extra Sauce", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 2,
  },
  {
    id: 26,
    name: "Spaghetti Carbonara",
    description: "Italian spaghetti with creamy carbonara sauce.",
    regularPrice: 420,
    sellPrice: 400,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3799616.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 400 },
      { id: 2, name: "Half Quarter", price: 300 },
      { id: 3, name: "full", price: 750 },
    ],
    addOns: [
      { id: 2601, name: "Extra Sauce", sellPrice: 29 },
      { id: 2602, name: "More Cheese", sellPrice: 50 },
    ],
    relatedItems: [
      {
        id: 4,
        name: "Pepperoni Pizza",
        sellPrice: 480,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 6,
  },
  {
    id: 27,
    name: "Caesar Salad",
    description: "Classic Caesar salad with croutons and dressing.",
    regularPrice: 280,
    sellPrice: 250,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/6319353.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 250 },
      { id: 2, name: "Half Quarter", price: 180 },
      { id: 3, name: "full", price: 500 },
    ],
    addOns: [
      { id: 2701, name: "Extra Croutons", sellPrice: 20 },
      { id: 2702, name: "More Dressing", sellPrice: 15 },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 6,
        name: "Spaghetti Carbonara",
        sellPrice: 400,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 28,
    name: "Salmon Sushi Roll",
    description: "Fresh salmon sushi roll with wasabi and soy sauce.",
    regularPrice: 600,
    sellPrice: 580,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3065728.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 580 },
      { id: 2, name: "Half Quarter", price: 400 },
      { id: 3, name: "full", price: 1200 },
    ],
    addOns: [
      { id: 2801, name: "More Wasabi", sellPrice: 20 },
      { id: 2802, name: "Extra Soy Sauce", sellPrice: 15 },
    ],
    relatedItems: [
      {
        id: 3,
        name: "Chicken Grilled",
        sellPrice: 280,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 8,
  },
  {
    id: 29,
    name: "Grilled Shrimp",
    description: "Grilled shrimp with garlic butter and lemon.",
    regularPrice: 700,
    sellPrice: 680,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/3515847.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 680 },
      { id: 2, name: "Half Quarter", price: 480 },
      { id: 3, name: "full", price: 1300 },
    ],
    addOns: [
      { id: 2901, name: "Extra Lemon", sellPrice: 15 },
      { id: 2902, name: "More Garlic Butter", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 8,
        name: "Salmon Sushi Roll",
        sellPrice: 580,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 10,
        name: "T-Bone Steak",
        sellPrice: 1150,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 1,
  },
  {
    id: 30,
    name: "T-Bone Steak",
    description: "Grilled T-bone steak with mashed potatoes.",
    regularPrice: 1200,
    sellPrice: 1150,
    image:
      "https://images.deliveryhero.io/image/fd-bd/Products/8310492.jpg??width=400",
    variation: [
      { id: 1, name: "half", price: 1150 },
      { id: 2, name: "Half Quarter", price: 800 },
      { id: 3, name: "full", price: 1600 },
    ],
    addOns: [
      { id: 3001, name: "More Mashed Potatoes", sellPrice: 50 },
      { id: 3002, name: "Extra Sauce", sellPrice: 29 },
    ],
    relatedItems: [
      {
        id: 5,
        name: "Mutton Burger",
        sellPrice: 320,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 7,
        name: "Caesar Salad",
        sellPrice: 250,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
      {
        id: 9,
        name: "Grilled Shrimp",
        sellPrice: 680,
        image: "https://your-image-link.com/salmon-sushi-roll.jpg",
      },
    ],
    categoryId: 10,
  },
];

// Helper function to generate random items
export const generateItems = (count: number): Item[] => {
  const items: Item[] = [];
  for (let i = 1; i <= count; i++) {
    items.push({
      id: i,
      name: `Cuban Wings Item no ${i}`,
      description: ` 1:1 - Light and delicate broth with tender chicken & subtle herbs Item ${i} Description`,
      price: Math.floor(Math.random() * 900) + 100, // Generate random price between 100 and 999
    });
  }
  return items;
};

// Generate 100 items
export const items = foods;
// export const items = generateItems(100);
