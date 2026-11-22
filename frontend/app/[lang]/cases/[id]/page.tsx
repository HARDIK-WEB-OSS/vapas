import { Suspense } from "react";

import { CaseView } from "@/components/case-view";

export default function Page() {
  return (
    <Suspense>
      <CaseView />
    </Suspense>
  );
}
