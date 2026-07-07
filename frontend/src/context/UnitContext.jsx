import { createContext, useContext, useEffect, useState } from "react";
import { detectDeviceUnitSystem, getUnitSystem, setUnitSystem } from "@/utils/units";

const UnitContext = createContext({
  unitSystem: "metric",
  setUnitSystem: () => {},
});

export const UnitProvider = ({ children }) => {
  const [unitSystem, setUnitSystemState] = useState(() => getUnitSystem());

  useEffect(() => {
    // On first mount, ensure we respect the priority:
    // 1) explicit user choice (already handled by getUnitSystem)
    // 2) device region
    // 3) metric
    const effective = getUnitSystem() || detectDeviceUnitSystem();
    if (effective !== unitSystem) {
      setUnitSystemState(effective);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const updateUnitSystem = (system) => {
    if (system !== "metric" && system !== "imperial") return;
    setUnitSystem(system);
    setUnitSystemState(system);
  };

  return (
    <UnitContext.Provider value={{ unitSystem, setUnitSystem: updateUnitSystem }}>
      {children}
    </UnitContext.Provider>
  );
};

export const useUnitSystem = () => {
  return useContext(UnitContext);
};

