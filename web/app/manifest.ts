import type { MetadataRoute } from "next";

/**
 * The installed app's identity (P9-T01).
 *
 * Served at `/manifest.webmanifest` by Next. It says "this is a standalone app
 * that starts at the dashboard", and it names the icons a launcher needs —
 * including a maskable one, because Android crops the icon to its own shape.
 *
 * Colours come from the design tokens so the splash screen already looks like
 * the first screen.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "STEM Games",
    short_name: "STEM Games",
    description: "Play games, earn points, and see how your school is doing this week.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f8fafd",
    theme_color: "#f8fafd",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
