import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "NeuroAd Internal ML",
  description: "Private ML operations control plane."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
