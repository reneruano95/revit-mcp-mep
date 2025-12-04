# Head Loss Calculations

The primary method for calculating head loss (friction loss) in a rectangular duct involves using the Darcy-Weisbach equation with the hydraulic diameter as the characteristic length. The equivalent round duct method is also widely used in HVAC design.

## Darcy-Weisbach Method (with Hydraulic Diameter)

This is the most accurate method and is valid for any fluid (liquid or gas) and flow regime (laminar or turbulent).

### 1. Calculate the Hydraulic Diameter ($D_{h}$)

For a rectangular duct with width ($W$) and height ($H$), the hydraulic diameter is used in place of the diameter in the standard Darcy-Weisbach equation.

$$D_{h}=\frac{4\times \text{Area}}{\text{Perimeter}}=\frac{4WH}{2(W+H)}$$

### 2. Determine the Flow Regime (Reynolds Number, $Re$)

Calculate the Reynolds number to determine if the flow is laminar or turbulent, which dictates how the friction factor is found.

$$Re=\frac{V\times D_{h}}{\nu }$$

where $V$ is the fluid velocity and $\nu$ is the kinematic viscosity of the fluid.

### 3. Calculate the Friction Factor ($f$)

*   **Laminar Flow ($Re\le 2300$):** The friction factor is simply $f=\frac{64}{Re}$.
*   **Turbulent Flow ($Re>4000$):** The friction factor depends on both the Reynolds number and the duct's relative roughness ($\epsilon /D_{h}$). This typically requires using the Colebrook-White equation or a Moody chart for circular pipes, adjusted for the rectangular cross-section.

### 4. Apply the Darcy-Weisbach Equation

Substitute the calculated friction factor, hydraulic diameter, length of the duct ($L$), and fluid velocity into the equation to find the head loss ($h_{f}$).

$$h_{f}=f\times \frac{L}{D_{h}}\times \frac{V^{2}}{2g}$$

where $g$ is the acceleration due to gravity.

## Equivalent Round Duct Method

This common HVAC design method converts the rectangular duct into an equivalent circular duct that would have the same friction loss for the same airflow rate.

### 1. Calculate the Equivalent Diameter ($D_{e}$)

The equivalent round duct diameter for a rectangular duct (with width $a$ and height $b$) is often calculated using the following empirical formula, based on ASHRAE guidelines:

$$D_{e}=1.3\times \frac{(ab)^{0.625}}{(a+b)^{0.25}}$$

### 2. Use Standard Duct Friction Charts

Once the equivalent diameter is found, standard friction loss charts (often called ductulators) for circular ducts can be used to determine the pressure loss per unit length. These charts are widely available and used in industry.

## Accounting for Minor Losses

Fittings, bends, transitions, dampers, and other components in a duct system also contribute to total head loss (minor losses). These are typically calculated using loss coefficients ($C_{o}$ or $k$) or by the equivalent length method:

$$\Delta P=C_{o}\times \text{Velocity\ Pressure}$$

These minor losses are added to the major (friction) losses to determine the total system head loss.

---

## Example: Duct Sizing for 1000 CFM and 0.08 Head Loss

**Question:** What should be the size of the ducts for 1000 cfm and 0.08 of head loss?

For an airflow of 1000 CFM and a friction loss rate of 0.08 inches of water gauge per 100 feet of duct length, the required duct sizes are approximately:

*   **Round Duct:** 14-inch diameter
*   **Rectangular Duct:** A range of sizes may be used, with common options including 8x22 inches, 10x18 inches, or 12x16 inches (width x height).

### Common Rectangular Duct Size Options

The specific dimensions of the rectangular duct can vary depending on space constraints and desired aspect ratio (a ratio close to 1:1 is generally most efficient). The following options all provide a similar friction loss of approximately 0.08 in. w.g. per 100 ft at 1000 CFM:

*   8 x 22 inches
*   10 x 18 inches
*   12 x 16 inches
*   14 x 14 inches (approximately square)

### Key Considerations

*   **Aspect Ratio:** Aim for an aspect ratio (width divided by height) as close to 1 as possible (square) for maximum efficiency and minimum material cost. Avoid aspect ratios greater than 4:1 if possible.
*   **Air Velocity:** For 1000 CFM, the air velocity in these duct sizes is typically within the recommended range of 600–1,000 FPM for main ducts in commercial or residential systems.
*   **Total System Head Loss:** The provided 0.08 in. w.g./100 ft is only the friction loss for the straight sections (major loss). The total system head loss must also account for minor losses from fittings, elbows, transitions, and grilles. The duct sizing must accommodate the available external static pressure from the air handler.
