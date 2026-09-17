# Ready2Rent — Domain Research & Intake Requirements

> Source basis: City of Calgary secondary suite pages and permit checklists (calgary.ca), reviewed September 2026. **Municipal rules change** — treat this as the model's starting knowledge and verify current requirements on calgary.ca before relying on any specific detail.

## 1. Positioning note (important)
The City of Calgary **Secondary Suite Incentive Program** offered up to **$10,000** per qualifying homeowner, but as of **June 24, 2026** new applications were moved to a **waitlist**, and the program is winding down (the federal Housing Accelerator Fund backing it was closing around September 2026).

**Implication:** do not build the core value proposition around securing the grant. Center it on removing the **time, uncertainty, and bureaucratic** barrier — the durable problem. Treat "incentive eligibility/assistance" as an optional, clearly-caveated module that can be toggled off.

## 2. Two application paths (the intake must branch on this)
1. **New secondary suite** — designing and building a suite from scratch to current code.
2. **Legalize an existing (unpermitted) suite** — bringing an already-built suite up to code and registering it.

The intake's first branching question sets which document set and which compliance checklist applies.

## 3. Permit stack (model as related records, not one permit)
- **Development Permit (DP)** — required only if a secondary suite is *not* a permitted use in the property's land use district. Confirm the district first.
- **Building Permit (BP)** — for the structural/safety work; plans must conform to the Alberta Building Code / National Building Code (Alberta Edition).
- **Trade permits** — separate permits for **electrical, plumbing, gas, and mechanical/HVAC** as applicable.

## 4. Documents homeowners must submit
Track these as a **checklist that varies by path**.

### Common to most applications
- Completed application form
- Site plan (property outline, dimensions, buildings, parking, distances to property lines)
- Floor plans for each level, rooms labeled by purpose, with dimensions
- Elevations (mainly new builds / exterior changes)
- Abandoned Well Declaration
- Site Contamination Statement
- Public Tree Disclosure Statement
- Asbestos abatement form — **if the home predates 1990**
- Proof of ownership (land title; possibly purchase agreement / possession letter)

### Additional for legalizing an existing suite — colour photos (combined into one file)
- Entryway from outside (incl. stairwell if applicable)
- Entryway from inside (incl. stairwell if applicable)
- Kitchen (all cooking appliances visible)
- Bathroom
- Parking area (on-property)
- Outdoor amenity / yard space for tenants
- Mechanical/furnace room showing the ceiling
- Each bedroom/sleeping-area window — one photo inside AND one outside

### For the incentive program (if/when applicable)
- Building permit number (required at time of application)
- Conditional approval sought **before** starting work (approvals valid ~6 months)
- Paid receipts submitted after inspections pass (rebate is post-completion, not upfront)

## 5. Compliance items (seed the ComplianceItem checklist)
Recurring code items that determine feasibility and cost — map directly to `ComplianceItem`:
- Egress window(s) in each bedroom/sleeping area
- Minimum ceiling height
- Fire separation between suite and the rest of the dwelling
- Interconnected smoke + CO alarms (each bedroom, hallway, mechanical room, common area), interlinked with the rest of the home
- Separate / dedicated entrance
- Mechanical/furnace room separation
- On-property parking
- Outdoor amenity space for tenants

## 6. Correct process order (encode as the status flow)
Starting construction out of order can disqualify a homeowner from the incentive — the ordering is a real constraint:
1. Confirm land use district allows a suite → apply for DP if discretionary
2. (If pursuing incentive) apply to the program **before** any construction
3. Building permit + trade permits
4. Construction
5. Mandatory inspections (SCO may issue corrective actions or accept a Verification of Compliance)
6. Register the suite (secondary suite registry) — inspected + registered = "legal"
7. (If incentive) submit receipts → rebate issued after completion

Suggested status stages:
`intake → eligibility_check → development_permit → permits → construction → inspections → registered → complete`

## 7. Financing boundary (regulatory caution)
There is **no upfront payment** from the incentive; homeowners typically bridge costs with a HELOC or construction loan. Arranging or brokering financing is a **regulated activity** in Alberta. In the app, keep financing as a **"connect / guide"** step (surface options, capture that the homeowner wants help, hand off to a licensed party) — never something the software originates or brokers.

## 8. How this maps to the data model
- **Suite** → `suite_type: new | legalize_existing` drives the whole flow
- **Property** → land use district → drives whether a DP is needed
- **Document** → typed against §4; required set depends on Suite.type and home age (asbestos)
- **ComplianceItem** → seeded from §5
- **Permit** → one per DP/BP/trade permit, each with its own status
- **StatusHistory** → transitions follow §6
- **Visit** → maps to City inspections
