// The two ways this page can hold no records — kept apart, because they are not the same
// news and they need opposite things from the clinician.
//
//   • "no-grant": the patient has approved nothing for you. The next step is to ask.
//   • "granted-empty": your grant is live, and the patient holds nothing in what they
//     approved. There is no next step; asking again would achieve nothing.
//
// The API distinguishes them through `grantedCategories`, and granted/view.ts turns that
// into two variants rather than one flag, so a caller cannot collapse them by accident.
// One component, because the geometry is shared; two renderings, because the meaning is not.

import { FolderOpen, ShieldQuestion } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, Card, CardContent } from "@pulseos/ui";

import { joinCategories } from "@/granted/view";

export type EmptyGrantedRecordsProps =
  | { variant: "no-grant"; patientHealthId: string }
  | { variant: "granted-empty"; patientHealthId: string; categories: readonly string[] };

export function EmptyGrantedRecords(props: EmptyGrantedRecordsProps) {
  const noGrant = props.variant === "no-grant";
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          {noGrant ? (
            <ShieldQuestion className="size-7" aria-hidden />
          ) : (
            <FolderOpen className="size-7" aria-hidden />
          )}
        </span>

        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">
            {noGrant ? "No access granted yet" : "Nothing here yet"}
          </p>
          <p className="text-muted-foreground mx-auto max-w-md text-sm leading-relaxed">
            {noGrant ? (
              <>
                <span className="font-mono text-[13px]">{props.patientHealthId}</span> has not
                approved any of your requests, so there is nothing you can open. Ask for the kinds
                of record you need and they will decide category by category.
              </>
            ) : (
              <>
                You have access to {joinCategories(props.categories)}, but{" "}
                <span className="font-mono text-[13px]">{props.patientHealthId}</span> holds no
                records in {props.categories.length === 1 ? "it" : "those"} yet. Nothing more to ask
                for — new records will appear here as hospitals add them.
              </>
            )}
          </p>
        </div>

        {noGrant ? (
          <Button asChild variant="outline" size="sm">
            <Link to={`/patients?healthId=${encodeURIComponent(props.patientHealthId)}`}>
              Request access
            </Link>
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
