"use client";

import HomeClient from "../../HomeClient";
import DemoImplementationSection from "../DemoImplementationSection";

export default function DemoContentClient() {
  return (
    <HomeClient
      isGuest
      demoMode
      initialMode="content"
      hubHref="/demo"
      architectureFooter={<DemoImplementationSection mode="content" />}
    />
  );
}
