import { create } from "zustand";
import type { Segment } from "./types";

type ExplorerState = {
  selectedSegment?: Segment;
  setSelectedSegment: (segment?: Segment) => void;
};

export const useExplorerStore = create<ExplorerState>((set) => ({
  selectedSegment: undefined,
  setSelectedSegment: (segment) => set({ selectedSegment: segment })
}));
