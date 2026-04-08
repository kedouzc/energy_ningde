import solver from 'javascript-lp-solver';

export interface Asset {
  id: string;
  name: string;
  type: 'stock' | 'cash';
  style?: string; // e.g., 'high-dividend', 'white-horse', 'growth'
  currentPrice: number;
  targetPrice: number;
  certainty: number;
  risk: number; // 0 to 100
}

export interface Constraints {
  maxRisk: number; // 0 to 100
  maxAssets: number; // integer
  maxSingleWeight: number; // 0 to 100
  minCash: number; // 0 to 100
  styleAllocations?: Record<string, number>; // e.g., { 'high-dividend': 50 }
}

export interface AllocationResult {
  allocations: { [id: string]: number };
  totalBounty: number;
  shadowPrices: {
    risk: number;
    bandwidth: number;
    singleLimit: number;
  };
}

export function solveAllocation(assets: Asset[], constraints: Constraints): AllocationResult {
  const cashReturn = 2.0; // Base cash return
  const mismatchOptionValue = 1.5; // Value of holding cash for future opportunities
  const totalCashValue = cashReturn + mismatchOptionValue;

  const buildModel = (c: Constraints, isRelaxed: boolean = false) => {
    const model: any = {
      optimize: 'bounty',
      opType: 'max',
      constraints: {
        totalWeight: { equal: 100 },
        maxRisk: { max: c.maxRisk * 100 },
        maxAssets: { max: c.maxAssets },
        minCash: { min: c.minCash },
      },
      variables: {},
      ints: {},
    };

    if (c.styleAllocations) {
      Object.entries(c.styleAllocations).forEach(([style, maxWeight]) => {
        model.constraints[`style_${style}`] = { max: maxWeight };
      });
    }

    // Add Cash variable
    model.variables['cash'] = {
      bounty: totalCashValue,
      totalWeight: 1,
      minCash: 1,
    };

    assets.forEach((asset) => {
      if (asset.type === 'cash') return;

      const margin = ((asset.targetPrice - asset.currentPrice) / asset.currentPrice) * 100;
      const bounty = margin * asset.certainty;

      // Continuous weight variable w_i
      const wVars: any = {
        bounty: bounty,
        totalWeight: 1,
        maxRisk: asset.risk,
        [`limit_${asset.id}`]: 1,
      };
      
      if (asset.style && c.styleAllocations && c.styleAllocations[asset.style] !== undefined) {
        wVars[`style_${asset.style}`] = 1;
      }

      model.variables[`w_${asset.id}`] = wVars;

      // Binary selection variable y_i
      model.variables[`y_${asset.id}`] = {
        maxAssets: 1,
        [`limit_${asset.id}`]: -c.maxSingleWeight,
        [`binary_${asset.id}`]: 1,
      };

      // Constraint: w_i - maxSingleWeight * y_i <= 0
      model.constraints[`limit_${asset.id}`] = { max: 0 };
      // Constraint: y_i <= 1
      model.constraints[`binary_${asset.id}`] = { max: 1 };

      if (!isRelaxed) {
        model.ints[`y_${asset.id}`] = 1;
      }
    });

    return model;
  };

  // 1. Solve the actual MILP
  const mainModel = buildModel(constraints);
  const mainResult: any = solver.Solve(mainModel);

  // Parse allocations
  const allocations: { [id: string]: number } = {};
  let totalAllocated = 0;
  
  if (mainResult.feasible) {
    assets.forEach((a) => {
      if (a.type !== 'cash') {
        const w = mainResult[`w_${a.id}`] || 0;
        allocations[a.id] = w;
        totalAllocated += w;
      }
    });
    allocations['cash'] = mainResult['cash'] || (100 - totalAllocated);
  } else {
    // Fallback if infeasible
    allocations['cash'] = 100;
  }

  // 2. Calculate Shadow Prices (Marginal Values) by perturbing constraints
  // We use the relaxed LP to get smoother marginal values, or just perturb the MILP.
  // Perturbing MILP is more accurate for the user's actual situation.
  
  const calcMarginal = (perturbedConstraints: Constraints) => {
    const res: any = solver.Solve(buildModel(perturbedConstraints));
    return res.feasible ? Math.max(0, res.result - mainResult.result) : 0;
  };

  const shadowPrices = {
    risk: calcMarginal({ ...constraints, maxRisk: constraints.maxRisk + 1 }), // Value of 1% more risk
    bandwidth: calcMarginal({ ...constraints, maxAssets: constraints.maxAssets + 1 }), // Value of 1 more asset slot
    singleLimit: calcMarginal({ ...constraints, maxSingleWeight: constraints.maxSingleWeight + 1 }), // Value of 1% more single weight
  };

  return {
    allocations,
    totalBounty: mainResult.feasible ? mainResult.result : 0,
    shadowPrices,
  };
}
