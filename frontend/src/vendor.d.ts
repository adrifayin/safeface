// Minimal typings for the two untyped libraries (avoids extra @types packages).
declare module "plotly.js-dist-min" {
  const Plotly: {
    newPlot(el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown): Promise<unknown>;
    purge(el: HTMLElement): void;
  };
  export default Plotly;
}

declare module "openseadragon" {
  interface TiledImage {
    setOpacity(o: number): void;
  }
  interface World {
    getItemAt(i: number): TiledImage | undefined;
    getItemCount(): number;
    removeItem(item: TiledImage): void;
  }
  interface Viewer {
    world: World;
    open(tileSource: unknown): void;
    addTiledImage(opts: {
      tileSource: unknown;
      opacity?: number;
      x?: number;
      y?: number;
      width?: number;
      success?: (e: { item: TiledImage }) => void;
    }): void;
    addHandler(name: string, fn: (e: unknown) => void): void;
    destroy(): void;
  }
  function OpenSeadragon(opts: Record<string, unknown>): Viewer;
  export default OpenSeadragon;
  export type { Viewer, TiledImage };
}
