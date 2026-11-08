declare module "plotly.js-cartesian-dist-min" {
  type PlotRecord = Record<string, unknown>;

  interface PlotlyStatic {
    react(root: HTMLElement, data: PlotRecord[], layout?: PlotRecord, config?: PlotRecord): Promise<HTMLElement>;
    purge(root: HTMLElement): void;
    Plots: {
      resize(root: HTMLElement): void;
    };
  }

  const Plotly: PlotlyStatic;
  export default Plotly;
}
