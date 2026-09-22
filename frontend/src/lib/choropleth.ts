export interface ChoroplethScale {
  getColor: (val: number | null | undefined) => string;
  min: number;
  max: number;
}

export function computeChoroplethScale(values: number[]): ChoroplethScale {
  const valid = values.filter((v): v is number => typeof v === "number" && !isNaN(v));
  if (valid.length === 0) {
    return {
      getColor: (val) => (val === null || val === undefined ? "#162232" : "#1e293b"),
      min: 0,
      max: 0,
    };
  }

  const min = Math.min(...valid);
  const max = Math.max(...valid);

  // 4-stop gold/amber ramp on dark surface
  const ramp = ["#1e293b", "#5a451d", "#9b752b", "#e8b84b"];

  const getColor = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "#162232";
    if (min === max) return ramp[3];
    const fraction = (val - min) / (max - min);
    if (fraction < 0.25) return ramp[0];
    if (fraction < 0.5) return ramp[1];
    if (fraction < 0.75) return ramp[2];
    return ramp[3];
  };

  return { getColor, min, max };
}
