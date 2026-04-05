import { LogOut, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useAppTranslation } from "@/lib/i18n";
import { getInitials } from "@/lib/identity";

import "./ChatHeader.css";

interface ChatHeaderProps {
  adminMode?: boolean;
  avatarUrl?: string;
  canOpenSettings?: boolean;
  name: string;
  onOpenSettings?: () => void;
  onSignOut?: () => void;
}

export function ChatHeader({
  adminMode = false,
  avatarUrl,
  canOpenSettings = adminMode,
  name,
  onOpenSettings,
  onSignOut,
}: ChatHeaderProps) {
  const { t } = useAppTranslation();
  const initials = getInitials(name);
  const [showAvatarImage, setShowAvatarImage] = useState(Boolean(avatarUrl));
  const showSettingsButton = Boolean(canOpenSettings && onOpenSettings);
  const showActions = adminMode || showSettingsButton || Boolean(onSignOut);

  useEffect(() => {
    setShowAvatarImage(Boolean(avatarUrl));
  }, [avatarUrl]);

  return (
    <header className="chat-header">
      <div className="chat-header__inner">
        <div className="chat-header__identity">
          <Avatar className="chat-header__avatar" size="lg">
            {avatarUrl && showAvatarImage ? (
              <img
                alt={name}
                className="aspect-square size-full object-cover"
                onError={() => {
                  setShowAvatarImage(false);
                }}
                src={avatarUrl}
              />
            ) : null}
            {!showAvatarImage ? (
              <AvatarFallback>{initials}</AvatarFallback>
            ) : null}
          </Avatar>
          <div>
            <p className="chat-header__status">{t("common.chatStatus")}</p>
            <h1 className="chat-header__name">{name}</h1>
          </div>
        </div>

        {showActions ? (
          <div className="chat-header__actions">
            {adminMode ? (
              <Button asChild type="button" variant="outline">
                <Link to="/admin">{t("admin.link")}</Link>
              </Button>
            ) : null}
            {onSignOut ? (
              <Button onClick={onSignOut} type="button" variant="outline">
                <LogOut size={16} />
                {t("common.signOut")}
              </Button>
            ) : null}
            {showSettingsButton ? (
              <Button
                aria-label={t("common.profileSettings")}
                onClick={onOpenSettings}
                size="icon-sm"
                type="button"
                variant="outline"
              >
                <Settings size={18} />
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </header>
  );
}
