/**
 * SessionBadge – compact display for execution session identity.
 */

import React from "react";
import { useI18n } from "../../i18n/useI18n";

interface Props {
  sessionId: string | null | undefined;
}

export const SessionBadge: React.FC<Props> = ({ sessionId }) => {
  const { t } = useI18n();
  if (!sessionId) {
    return <span className="session-badge session-badge--none">{t("common", "unknown")}</span>;
  }
  return (
    <span className="session-badge" title={sessionId}>
      {sessionId}
    </span>
  );
};
