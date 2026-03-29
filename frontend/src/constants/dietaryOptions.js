/**
 * Dietary restriction, cuisine, equipment, intolerance, and diet option lists.
 * IDs match Spoonacular API parameter values exactly where applicable.
 */

// ---------------------------------------------------------------------------
// Spoonacular diet types — maps to the `diet` query parameter.
// Sorted for display; user selects one.
// ---------------------------------------------------------------------------
export const SPOONACULAR_DIETS = [
  { id: 'gluten free', label: 'Gluten Free' },
  { id: 'ketogenic', label: 'Ketogenic' },
  { id: 'lacto-vegetarian', label: 'Lacto-Vegetarian' },
  { id: 'low fodmap', label: 'Low FODMAP' },
  { id: 'ovo-vegetarian', label: 'Ovo-Vegetarian' },
  { id: 'paleo', label: 'Paleo' },
  { id: 'pescetarian', label: 'Pescetarian' },
  { id: 'primal', label: 'Primal' },
  { id: 'vegan', label: 'Vegan' },
  { id: 'vegetarian', label: 'Vegetarian' },
  { id: 'whole30', label: 'Whole30' },
];

// ---------------------------------------------------------------------------
// Spoonacular intolerances — maps to the `intolerances` query parameter.
// Alphabetized. User can select multiple.
// ---------------------------------------------------------------------------
export const INTOLERANCES = [
  { id: 'dairy', label: 'Dairy' },
  { id: 'egg', label: 'Egg' },
  { id: 'gluten', label: 'Gluten' },
  { id: 'grain', label: 'Grain' },
  { id: 'peanut', label: 'Peanut' },
  { id: 'seafood', label: 'Seafood' },
  { id: 'sesame', label: 'Sesame' },
  { id: 'shellfish', label: 'Shellfish' },
  { id: 'soy', label: 'Soy' },
  { id: 'sulfite', label: 'Sulfite' },
  { id: 'tree nut', label: 'Tree Nut' },
  { id: 'wheat', label: 'Wheat' },
];

// ---------------------------------------------------------------------------
// Intolerance → exclude ingredients mapping.
// Used to populate Spoonacular's `excludeIngredients` param as a safety net
// on top of the `intolerances` param.
// ---------------------------------------------------------------------------
export const INTOLERANCE_EXCLUDE_INGREDIENTS = {
  dairy: 'milk,butter,cream,cheese,yogurt,whey,lactose',
  egg: 'eggs,egg yolk,egg white',
  gluten: 'gluten,barley,rye,spelt',
  grain: 'wheat,barley,rye,oats,corn flour,buckwheat',
  peanut: 'peanuts,peanut butter,peanut oil',
  seafood: 'fish,salmon,tuna,cod,tilapia,halibut,sardine,anchovy',
  sesame: 'sesame,tahini,sesame oil,sesame seeds',
  shellfish: 'shrimp,crab,lobster,scallops,mussels,clams,oysters',
  soy: 'soy,tofu,edamame,soy sauce,tempeh,miso,soybean',
  sulfite: 'wine,dried fruit,vinegar,beer',
  'tree nut': 'almonds,walnuts,cashews,pecans,pistachios,hazelnuts,macadamia nuts',
  wheat: 'wheat,wheat flour,bread flour,semolina,spelt,durum',
};

// ---------------------------------------------------------------------------
// Cuisines
// ---------------------------------------------------------------------------
export const CUISINE_OPTIONS = [
  { id: 'italian', label: 'Italian' },
  { id: 'mexican', label: 'Mexican' },
  { id: 'chinese', label: 'Chinese' },
  { id: 'japanese', label: 'Japanese' },
  { id: 'indian', label: 'Indian' },
  { id: 'thai', label: 'Thai' },
  { id: 'mediterranean', label: 'Mediterranean' },
  { id: 'korean', label: 'Korean' },
  { id: 'american', label: 'American' },
  { id: 'french', label: 'French' },
  { id: 'middle eastern', label: 'Middle Eastern' },
  { id: 'vietnamese', label: 'Vietnamese' },
  { id: 'greek', label: 'Greek' },
  { id: 'caribbean', label: 'Caribbean' },
  { id: 'african', label: 'African' },
];

// ---------------------------------------------------------------------------
// Health goals (internal — not a direct Spoonacular param)
// ---------------------------------------------------------------------------
export const HEALTH_GOALS = [
  { id: 'weight-loss', label: 'Weight Loss' },
  { id: 'muscle-gain', label: 'Muscle Gain' },
  { id: 'maintenance', label: 'Maintenance' },
  { id: 'none', label: 'No Specific Goal' },
];

// ---------------------------------------------------------------------------
// Time preferences (internal)
// ---------------------------------------------------------------------------
export const TIME_PREFERENCES = [
  { id: 'quick', label: 'Quick', description: 'Under 20 minutes' },
  { id: 'moderate', label: 'Moderate', description: '20–45 minutes' },
  { id: 'extended', label: 'Extended', description: '45+ minutes' },
];

// ---------------------------------------------------------------------------
// Cooking equipment — sorted most popular first, IDs match Spoonacular's
// `equipment` parameter values exactly.
// ---------------------------------------------------------------------------
export const COOKING_EQUIPMENT = [
  // Tier 1 — Essential (virtually everyone has these)
  { id: 'oven', label: 'Oven' },
  { id: 'stove', label: 'Stove' },
  { id: 'microwave', label: 'Microwave' },
  { id: 'frying pan', label: 'Frying Pan' },
  { id: 'knife', label: 'Knife' },
  { id: 'cutting board', label: 'Cutting Board' },
  { id: 'pot', label: 'Pot' },
  { id: 'sauce pan', label: 'Sauce Pan' },
  { id: 'bowl', label: 'Bowl' },
  { id: 'mixing bowl', label: 'Mixing Bowl' },
  { id: 'spatula', label: 'Spatula' },
  { id: 'wooden spoon', label: 'Wooden Spoon' },
  { id: 'whisk', label: 'Whisk' },
  { id: 'measuring cup', label: 'Measuring Cup' },
  { id: 'measuring spoon', label: 'Measuring Spoon' },
  { id: 'baking sheet', label: 'Baking Sheet' },
  { id: 'colander', label: 'Colander' },
  { id: 'grater', label: 'Grater' },
  { id: 'peeler', label: 'Peeler' },
  { id: 'can opener', label: 'Can Opener' },
  { id: 'ladle', label: 'Ladle' },
  { id: 'tongs', label: 'Tongs' },
  { id: 'kitchen scissors', label: 'Kitchen Scissors' },
  { id: 'kitchen scale', label: 'Kitchen Scale' },
  { id: 'aluminum foil', label: 'Aluminum Foil' },
  { id: 'plastic wrap', label: 'Plastic Wrap' },
  { id: 'baking paper', label: 'Baking Paper' },
  // Tier 2 — Common appliances & cookware
  { id: 'blender', label: 'Blender' },
  { id: 'food processor', label: 'Food Processor' },
  { id: 'hand mixer', label: 'Hand Mixer' },
  { id: 'stand mixer', label: 'Stand Mixer' },
  { id: 'airfryer', label: 'Air Fryer' },
  { id: 'instant pot', label: 'Instant Pot' },
  { id: 'slow cooker', label: 'Slow Cooker' },
  { id: 'rice cooker', label: 'Rice Cooker' },
  { id: 'pressure cooker', label: 'Pressure Cooker' },
  { id: 'toaster', label: 'Toaster' },
  { id: 'grill', label: 'Grill' },
  { id: 'grill pan', label: 'Grill Pan' },
  { id: 'wok', label: 'Wok' },
  { id: 'dutch oven', label: 'Dutch Oven' },
  { id: 'roasting pan', label: 'Roasting Pan' },
  { id: 'casserole dish', label: 'Casserole Dish' },
  { id: 'baking pan', label: 'Baking Pan' },
  { id: 'springform pan', label: 'Springform Pan' },
  { id: 'loaf pan', label: 'Loaf Pan' },
  { id: 'muffin tray', label: 'Muffin Tray' },
  { id: 'wire rack', label: 'Wire Rack' },
  { id: 'kitchen thermometer', label: 'Kitchen Thermometer' },
  { id: 'rolling pin', label: 'Rolling Pin' },
  { id: 'pastry brush', label: 'Pastry Brush' },
  { id: 'mortar and pestle', label: 'Mortar and Pestle' },
  { id: 'sieve', label: 'Sieve' },
  { id: 'box grater', label: 'Box Grater' },
  { id: 'immersion blender', label: 'Immersion Blender' },
  { id: 'deep fryer', label: 'Deep Fryer' },
  { id: 'mandoline', label: 'Mandoline' },
  { id: 'zester', label: 'Zester' },
  { id: 'microplane', label: 'Microplane' },
  // Tier 3 — Bakeware & specialty
  { id: 'cake form', label: 'Cake Form' },
  { id: 'pie form', label: 'Pie Form' },
  { id: 'tart form', label: 'Tart Form' },
  { id: 'pizza stone', label: 'Pizza Stone' },
  { id: 'pizza pan', label: 'Pizza Pan' },
  { id: 'pizza cutter', label: 'Pizza Cutter' },
  { id: 'waffle iron', label: 'Waffle Iron' },
  { id: 'double boiler', label: 'Double Boiler' },
  { id: 'steamer basket', label: 'Steamer Basket' },
  { id: 'panini press', label: 'Panini Press' },
  { id: 'pasta machine', label: 'Pasta Machine' },
  { id: 'candy thermometer', label: 'Candy Thermometer' },
  { id: 'salad spinner', label: 'Salad Spinner' },
  { id: 'slotted spoon', label: 'Slotted Spoon' },
  { id: 'potato masher', label: 'Potato Masher' },
  { id: 'ramekin', label: 'Ramekin' },
  { id: 'broiler', label: 'Broiler' },
  { id: 'broiler pan', label: 'Broiler Pan' },
  { id: 'griddle', label: 'Griddle' },
  { id: 'dehydrator', label: 'Dehydrator' },
  { id: 'juicer', label: 'Juicer' },
  { id: 'lemon squeezer', label: 'Lemon Squeezer' },
  { id: 'cheesecloth', label: 'Cheesecloth' },
  { id: 'pastry bag', label: 'Pastry Bag' },
  { id: 'pastry cutter', label: 'Pastry Cutter' },
  { id: 'dough scraper', label: 'Dough Scraper' },
  { id: 'offset spatula', label: 'Offset Spatula' },
  { id: 'silicone muffin tray', label: 'Silicone Muffin Tray' },
  { id: 'silicone muffin liners', label: 'Silicone Muffin Liners' },
  { id: 'muffin liners', label: 'Muffin Liners' },
  { id: 'mini muffin tray', label: 'Mini Muffin Tray' },
  { id: 'glass baking pan', label: 'Glass Baking Pan' },
  { id: 'glass casserole dish', label: 'Glass Casserole Dish' },
  { id: 'canning jar', label: 'Canning Jar' },
  { id: 'ice cream machine', label: 'Ice Cream Machine' },
  { id: 'tajine pot', label: 'Tajine Pot' },
  { id: 'bread machine', label: 'Bread Machine' },
  { id: 'popcorn maker', label: 'Popcorn Maker' },
  // Tier 4 — Specialized / occasional use
  { id: 'baking spatula', label: 'Baking Spatula' },
  { id: 'garlic press', label: 'Garlic Press' },
  { id: 'meat grinder', label: 'Meat Grinder' },
  { id: 'meat tenderizer', label: 'Meat Tenderizer' },
  { id: 'chefs knife', label: "Chef's Knife" },
  { id: 'bread knife', label: 'Bread Knife' },
  { id: 'fillet knife', label: 'Fillet Knife' },
  { id: 'serrated knife', label: 'Serrated Knife' },
  { id: 'cleaver', label: 'Cleaver' },
  { id: 'mincing knife', label: 'Mincing Knife' },
  { id: 'carving fork', label: 'Carving Fork' },
  { id: 'poultry shears', label: 'Poultry Shears' },
  { id: 'apple corer', label: 'Apple Corer' },
  { id: 'apple cutter', label: 'Apple Cutter' },
  { id: 'cherry pitter', label: 'Cherry Pitter' },
  { id: 'egg slicer', label: 'Egg Slicer' },
  { id: 'melon baller', label: 'Melon Baller' },
  { id: 'potato ricer', label: 'Potato Ricer' },
  { id: 'funnel', label: 'Funnel' },
  { id: 'pepper grinder', label: 'Pepper Grinder' },
  { id: 'palette knife', label: 'Palette Knife' },
  { id: 'sifter', label: 'Sifter' },
  { id: 'pizza board', label: 'Pizza Board' },
  { id: 'ceramic pie form', label: 'Ceramic Pie Form' },
  { id: 'madeleine form', label: 'Madeleine Form' },
  { id: 'kugelhopf pan', label: 'Kugelhopf Pan' },
  { id: 'silicone kugelhopf pan', label: 'Silicone Kugelhopf Pan' },
  { id: 'heart shaped cake form', label: 'Heart Shaped Cake Form' },
  { id: 'heart shaped silicone form', label: 'Heart Shaped Silicone Form' },
  { id: 'chocolate mold', label: 'Chocolate Mold' },
  { id: 'cake pop mold', label: 'Cake Pop Mold' },
  { id: 'blow torch', label: 'Blow Torch' },
  { id: 'ice cube tray', label: 'Ice Cube Tray' },
  { id: 'popsicle molds', label: 'Popsicle Molds' },
  { id: 'wax paper', label: 'Wax Paper' },
  { id: 'kitchen towels', label: 'Kitchen Towels' },
  { id: 'kitchen twine', label: 'Kitchen Twine' },
  { id: 'ziploc bags', label: 'Ziploc Bags' },
  { id: 'toothpicks', label: 'Toothpicks' },
  { id: 'wooden skewers', label: 'Wooden Skewers' },
  { id: 'metal skewers', label: 'Metal Skewers' },
  { id: 'skewers', label: 'Skewers' },
  { id: 'chopsticks', label: 'Chopsticks' },
  { id: 'butter curler', label: 'Butter Curler' },
  { id: 'gravy boat', label: 'Gravy Boat' },
  { id: 'baster', label: 'Baster' },
  { id: 'oven mitt', label: 'Oven Mitt' },
  { id: 'pot holder', label: 'Pot Holder' },
  { id: 'kitchen timer', label: 'Kitchen Timer' },
  { id: 'bottle opener', label: 'Bottle Opener' },
  { id: 'corkscrew', label: 'Corkscrew' },
  { id: 'cake server', label: 'Cake Server' },
];

// Legacy alias — kept so old imports of DIETARY_RESTRICTIONS still work
// (the onboarding now uses SPOONACULAR_DIETS + INTOLERANCES directly)
export const DIETARY_RESTRICTIONS = SPOONACULAR_DIETS;
